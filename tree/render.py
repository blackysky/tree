"""
Tree rendering and output writing.

This module is responsible for one thing: transforming an annotated list[Node]
into a formatted text tree and writing it to disk. It performs no scanning,
detection, or annotation.

Rendering relies on three guarantees established by the scanning stage and the Node structure:
  - Nodes are in parent-before-child order.
  - node.depth is the absolute depth from root (root children = depth 1).
  - The root node itself is not in the node list.

Output structure:
  - A two-line metadata header (Project, Environment).
  - A blank separator line.
  - The tree body, whose first line is always root.name + "/", followed
    by one line per node in the list.

Branch markers are chosen per-node by scanning forward to find the first
subsequent node at depth <= current. If that node is shallower, or none
exists, the current node is the last child of its parent. This correctly
handles directory nodes whose immediately following node is a child (deeper),
not a sibling.

A set of open_depths tracks which depth columns still have pending siblings
below the current rendering position, driving the pipe vs space choice for
each indentation column.

Output is fully deterministic: no timestamps or run-specific data appear in
the rendered text. Identical input always produces identical output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tree.shared_types import Node

if TYPE_CHECKING:
    from tree.config import Config

# ---------------------------------------------------------------------------
# Tree drawing characters
# ---------------------------------------------------------------------------

_UNICODE_BRANCH = "├── "
_UNICODE_LAST = "└── "
_UNICODE_PIPE = "│   "
_UNICODE_SPACE = "    "

_ASCII_BRANCH = "+-- "
_ASCII_LAST = "+-- "  # ASCII mode uses the same character for both
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

    lines: list[str] = [config.root.name + "/"]

    # open_depths: the set of depths that still have pending siblings below
    # the current position. For each indentation column at depth d, draw a
    # pipe if d is in open_depths, a space otherwise.
    open_depths: set[int] = set()

    for i, node in enumerate(nodes):
        depth = node.depth

        # Determine whether this node is the last child of its parent.
        # A one-step lookahead is insufficient: the immediately following node
        # may be a child of the current node (deeper), not a sibling.
        # Scan forward to find the first subsequent node at depth <= current:
        #   - if none exists          -> current node is last
        #   - if that node is deeper  -> cannot happen (we stop at <=)
        #   - if that node is equal   -> a sibling follows; not last
        #   - if that node is shallower -> parent closes; current node is last
        is_last = True
        for j in range(i + 1, len(nodes)):
            if nodes[j].depth <= depth:
                is_last = nodes[j].depth < depth
                break

        # Update open_depths for this depth column.
        if is_last:
            open_depths.discard(depth)
        else:
            open_depths.add(depth)

        # Build the indentation prefix for ancestor columns (depths 1..depth-1).
        # Depth-1 nodes hang directly off the root - no prefix columns needed.
        prefix = "".join(
            pipe if d in open_depths else space
            for d in range(1, depth)
        )

        lines.append(prefix + (last if is_last else branch) + _format_label(node))

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
