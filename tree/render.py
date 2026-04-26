"""Tree rendering and output writing."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tree.config import Environment
from tree.shared_types import Node

if TYPE_CHECKING:
    from tree.config import Config

_ENV_NAME: dict[Environment, str] = {
    Environment.JAVA: "java",
    Environment.WEB: "web",
    Environment.UNKNOWN: "unknown",
}

_UNICODE_BRANCH = "├── "
_UNICODE_LAST = "└── "
_UNICODE_PIPE = "│   "
_UNICODE_SPACE = "    "

_ASCII_BRANCH = "+-- "
_ASCII_LAST = "+-- "
_ASCII_PIPE = "|   "
_ASCII_SPACE = "    "


def render_text(nodes: list[Node], config: Config) -> str:
    """Build the plain-text output."""
    header = _build_header(config)
    body = _build_tree(nodes, config)
    return header + "\n\n" + body


def write_output(text: str, config: Config) -> None:
    """Write text output to disk."""
    config.output_path.write_text(text, encoding="utf-8", newline="\n")


def render_json(nodes: list[Node], config: Config) -> str:
    """Build the JSON output."""
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

    stack: list[tuple[int, list[dict]]] = [(0, root_children)]

    for node in nodes:
        while stack[-1][0] >= node.depth:
            stack.pop()

        parent_children = stack[-1][1]
        node_dict = _build_node_dict(node)
        parent_children.append(node_dict)

        if node.is_dir and not node.is_collapsed_entry and not node.is_summary:
            stack.append((node.depth, node_dict["children"]))

    return json.dumps(document, ensure_ascii=False, indent=2)


def _build_node_dict(node: Node) -> dict:
    """Produce the JSON dict for a single node."""
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


def _build_header(config: Config) -> str:
    """Build the text header."""
    if config.env_overridden:
        env_line = f"Environment: {config.profile.name} (manual override)"
    else:
        confidence = config.detection_result.confidence.name.lower()
        env_line = f"Environment: {config.profile.name} ({confidence})"

    return f"Project: {config.root}\n{env_line}"


def _build_tree(nodes: list[Node], config: Config) -> str:
    if not nodes:
        return config.root.name + "/\n"

    use_ascii = config.use_ascii
    branch = _ASCII_BRANCH if use_ascii else _UNICODE_BRANCH
    last = _ASCII_LAST if use_ascii else _UNICODE_LAST
    pipe = _ASCII_PIPE if use_ascii else _UNICODE_PIPE
    space = _ASCII_SPACE if use_ascii else _UNICODE_SPACE

    n = len(nodes)
    is_last_flags: list[bool] = [False] * n
    pending: list[int] = []
    for j in range(n):
        d_j = nodes[j].depth
        while pending and nodes[pending[-1]].depth >= d_j:
            i = pending.pop()
            is_last_flags[i] = nodes[i].depth > d_j
        pending.append(j)
    for i in pending:
        is_last_flags[i] = True

    lines: list[str] = [config.root.name + "/"]

    open_depths: set[int] = set()

    for i, node in enumerate(nodes):
        depth = node.depth
        node_is_last = is_last_flags[i]

        if node_is_last:
            open_depths.discard(depth)
        else:
            open_depths.add(depth)

        prefix = "".join(pipe if d in open_depths else space for d in range(1, depth))

        lines.append(prefix + (last if node_is_last else branch) + _format_label(node))

    return "\n".join(lines) + "\n"


def _format_label(node: Node) -> str:
    """Format one node label."""
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
