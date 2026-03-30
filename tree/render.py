"""
Tree rendering and output writing.

This module is responsible for one thing: transforming an annotated list[Node]
into a formatted text tree and writing it to disk. It performs no scanning,
detection, or annotation.

Rendering relies on three guarantees established by the scanning stage and the Node structure:
  - Nodes are in parent-before-child order.
  - node.depth is the absolute depth from root (root children = depth 1).
  - The root node itself is not in the node list.

Output structure (text):
  - A two-line metadata header (Project, Environment).
  - A blank separator line.
  - The tree body, whose first line is always root.name + "/", followed
    by one line per node in the list.

Branch markers are chosen from precomputed last-child information.

Last-child status is resolved in a single O(n) forward pass before rendering:
each node remains pending until the first later node at depth <= its own depth
is encountered. A later node at the same depth makes it non-last; a shallower
node makes it last. Nodes left unresolved at the end are also last.

A set of open_depths tracks which depth columns still have pending siblings
below the current rendering position, driving the pipe vs space choice for
each indentation column.

Output structure (JSON):
  - A top-level object with project path, environment metadata, and a root
    node whose children mirror the scanned tree hierarchy.
  - Hierarchy is reconstructed from the flat node list using a depth stack
    in a single O(n) pass. No recursion required.

Output is fully deterministic: no timestamps or run-specific data appear in
either format. Identical input always produces identical output.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tree.config import Environment
from tree.shared_types import Node

if TYPE_CHECKING:
    from tree.config import Config

# Canonical machine-readable identifiers for each environment.
# Keyed on the Environment enum so the mapping is stable regardless of how
# EnvironmentProfile.name (a display label) might change in future profiles.
_ENV_NAME: dict[Environment, str] = {
    Environment.JAVA: "java",
    Environment.WEB: "web",
    Environment.UNKNOWN: "unknown",
}

# ---------------------------------------------------------------------------
# Tree drawing characters
# ---------------------------------------------------------------------------

_UNICODE_BRANCH = "├── "
_UNICODE_LAST = "└── "
_UNICODE_PIPE = "│   "
_UNICODE_SPACE = "    "

_ASCII_BRANCH = "+-- "
_ASCII_LAST = "+-- "
_ASCII_PIPE = "|   "
_ASCII_SPACE = "    "


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def render_text(nodes: list[Node], config: Config) -> str:
    """
    Build the full output text for the given node list and configuration.

    Returns the complete string including header and tree body, separated by
    a blank line. Does not write to disk - the caller (tree_cli.py) handles that.

    Output is fully deterministic: no timestamps or run-specific data appear.
    """
    header = _build_header(config)
    body = _build_tree(nodes, config)
    return header + "\n\n" + body


def write_output(text: str, config: Config) -> None:
    """
    Write the rendered text to config.output_path.

    Always uses UTF-8 encoding and Unix line endings regardless of platform.
    Raises OSError on failure - the caller handles error reporting.
    """
    config.output_path.write_text(text, encoding="utf-8", newline="\n")


def render_json(nodes: list[Node], config: Config) -> str:
    """
    Build a hierarchical JSON representation of the scanned project tree.

    Returns a formatted JSON string. Does not write to disk - the caller
    handles that via write_output(), which is reused unchanged.

    Hierarchy reconstruction
    ------------------------
    Nodes arrive in parent-before-child order with absolute depth values.
    A stack of (depth, children_list) pairs tracks the current ancestry chain.
    The root node is pre-seeded at depth 0. For each node:

      1. Pop the stack until the top entry's depth is strictly less than the
         current node's depth - that entry is the current node's parent.
      2. Build the node dict and append it to the parent's children list.
      3. If the node is a traversable directory (not a collapsed entry or
         summary), push (node.depth, node_dict["children"]) so that
         subsequent deeper nodes attach to it.

    Collapsed entries and summary nodes are always leaves - they are never
    pushed onto the stack regardless of their is_dir value.

    Environment block
    -----------------
    name:            stable lowercase identifier from the _ENV_NAME mapping.
                     When detection ran, derived from config.detection_result.environment.
                     When --env was used, the sentinel DetectionResult holds
                     Environment.UNKNOWN regardless of the chosen profile, so a
                     reverse lookup via _ENV_NAME against the profile's display
                     name is used instead.
    display_name:    config.profile.name as-is (human-readable label).
    manual_override: config.env_overridden.
    confidence:      omitted entirely when manual_override is True - detection
                     did not run so emitting a confidence value would be
                     structurally dishonest.

    Determinism
    -----------
    Input order is preserved. Nothing is sorted. Output is deterministic
    given identical input, matching the guarantee of render_text().
    """
    # Derive the stable machine name from the Environment enum where possible.
    # When detection ran, config.detection_result.environment is authoritative.
    # When --env was used, the sentinel holds Environment.UNKNOWN regardless of
    # the chosen profile, so fall back to a reverse lookup via _ENV_NAME using
    # the profile's display name. This keeps the mapping canonical in all cases.
    if not config.env_overridden:
        env_enum = config.detection_result.environment
    else:
        _name_to_env = {v: k for k, v in _ENV_NAME.items()}
        env_enum = _name_to_env.get(config.profile.name.lower(), Environment.UNKNOWN)

    env_block: dict = {
        "name": _ENV_NAME[env_enum],
        "display_name": config.profile.name,
        "manual_override": config.env_overridden,
    }
    if not config.env_overridden:
        env_block["confidence"] = config.detection_result.confidence.name.lower()

    root_children: list[dict] = []
    document: dict = {
        "project": str(config.root),
        "environment": env_block,
        "root": {
            "name": config.root.name,
            "type": "directory",
            "children": root_children,
        },
    }

    # Stack entries: (depth, children_list_of_that_node).
    # The root is pre-seeded at depth 0 so all depth-1 nodes attach to it.
    stack: list[tuple[int, list[dict]]] = [(0, root_children)]

    for node in nodes:
        # Pop until the parent depth is strictly less than this node's depth.
        while stack[-1][0] >= node.depth:
            stack.pop()

        parent_children = stack[-1][1]
        node_dict = _build_node_dict(node)
        parent_children.append(node_dict)

        # Only traversable directories are pushed; collapsed entries and
        # summary nodes are structural leaves and never become parents.
        if node.is_dir and not node.is_collapsed_entry and not node.is_summary:
            stack.append((node.depth, node_dict["children"]))

    return json.dumps(document, ensure_ascii=False, indent=2)


def _build_node_dict(node: Node) -> dict:
    """
    Produce the JSON dict for a single node.

    Summary nodes:         {"type": "summary", "label": "..."}
    Directory nodes:       {"name": ..., "type": "directory", "children": [...]}
                           + "symlink": true  if symlink
                           + "collapsed": true  if collapsed entry
    File nodes:            {"name": ..., "type": "file", "annotations": [...]}
                           + "symlink": true  if symlink
                           + "collapsed": true  if collapsed entry

    "children" is initialised to an empty list for all directory nodes.
    Collapsed directory entries receive "children" too - they are typed as
    directories but are leaves in the JSON tree (never pushed onto the stack).
    """
    if node.is_summary:
        return {"type": "summary", "label": node.summary_label}

    node_type = "directory" if node.is_dir else "file"
    result: dict = {"name": node.path.name, "type": node_type}

    if node.is_symlink:
        result["symlink"] = True

    if node.is_collapsed_entry:
        result["collapsed"] = True

    if node.is_dir:
        result["children"] = []
    else:
        result["annotations"] = list(node.annotations)

    return result


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _build_header(config: Config) -> str:
    """
    Build the metadata header block.

    When the environment was explicitly overridden via --env, the confidence
    label is omitted - detection was skipped entirely so it carries no meaning.

    No timestamp is included. The output must remain deterministic across
    runs on identical input; a live timestamp would break that guarantee.
    """
    if config.env_overridden:
        env_line = f"Environment: {config.profile.name} (manual override)"
    else:
        confidence = config.detection_result.confidence.name.lower()
        env_line = f"Environment: {config.profile.name} ({confidence})"

    return f"Project: {config.root}\n{env_line}"


# ---------------------------------------------------------------------------
# Tree body
# ---------------------------------------------------------------------------

def _build_tree(nodes: list[Node], config: Config) -> str:
    if not nodes:
        return config.root.name + "/\n"

    use_ascii = config.use_ascii
    branch = _ASCII_BRANCH if use_ascii else _UNICODE_BRANCH
    last = _ASCII_LAST if use_ascii else _UNICODE_LAST
    pipe = _ASCII_PIPE if use_ascii else _UNICODE_PIPE
    space = _ASCII_SPACE if use_ascii else _UNICODE_SPACE

    # Precompute is_last for every node in a single O(n) forward pass.
    #
    # A node at index i (depth d) is the last child of its parent iff the
    # first subsequent node at depth <= d is strictly shallower than d, or
    # no such node exists. A later node at the same depth only matters if it
    # arrives before the tree closes back to a shallower level; once a
    # shallower node is encountered the parent scope has closed and any
    # further same-depth nodes belong to a different parent entirely.
    #
    # A stack of unresolved indices drives the pass. When node j (depth d_j)
    # is processed, it is the first-later-node-at-depth-<= answer for every
    # pending node whose depth >= d_j:
    #
    #   pending depth > d_j  ->  first later node is shallower  ->  is_last
    #   pending depth == d_j ->  first later node is a sibling  ->  not last
    #
    # Each index is pushed once and popped once: O(n) total.
    n = len(nodes)
    is_last_flags: list[bool] = [False] * n
    # Stack of node indices whose is_last value has not yet been resolved.
    pending: list[int] = []
    for j in range(n):
        d_j = nodes[j].depth
        while pending and nodes[pending[-1]].depth >= d_j:
            i = pending.pop()
            is_last_flags[i] = nodes[i].depth > d_j  # shallower next -> last
        pending.append(j)
    # Nodes still on the stack have no subsequent node at depth <= their own;
    # the tree closes above them with no sibling following.
    for i in pending:
        is_last_flags[i] = True

    lines: list[str] = [config.root.name + "/"]

    # open_depths: the set of depths that still have pending siblings below
    # the current position. For each indentation column at depth d, draw a
    # pipe if d is in open_depths, a space otherwise.
    open_depths: set[int] = set()

    for i, node in enumerate(nodes):
        depth = node.depth
        node_is_last = is_last_flags[i]

        # Update open_depths for this depth column.
        if node_is_last:
            open_depths.discard(depth)
        else:
            open_depths.add(depth)

        # Build the indentation prefix for ancestor columns (depths 1..depth-1).
        # Depth-1 nodes hang directly off the root - no prefix columns needed.
        prefix = "".join(
            pipe if d in open_depths else space
            for d in range(1, depth)
        )

        lines.append(prefix + (last if node_is_last else branch) + _format_label(node))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Node label formatting
# ---------------------------------------------------------------------------

def _format_label(node: Node) -> str:
    """
    Produce the display label for a single node.

    Summary nodes:   render summary_label directly, no connector appended.
    Directory nodes: append trailing slash; append [symlink] if applicable.
    File nodes:      append [symlink] if symlink, otherwise annotation labels.
    """
    if node.is_summary:
        return node.summary_label

    name = node.path.name

    if node.is_dir:
        return name + "/" + (" [symlink]" if node.is_symlink else "")

    if node.is_symlink:
        return name + " [symlink]"

    if node.annotations:
        return name + " " + " ".join(f"[{a}]" for a in node.annotations)

    return name
