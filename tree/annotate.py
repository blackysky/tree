"""Annotation pipeline and rule implementations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from tree.shared_types import AnnotationRule, Node

if TYPE_CHECKING:
    # EnvironmentProfile is only referenced in type annotations at runtime.
    # The TYPE_CHECKING guard breaks the profiles -> annotate -> profiles cycle.
    from tree.profiles import EnvironmentProfile

ACTIVE_CODE_THRESHOLD: float = 0.05

_JAVA_COMMENT_PREFIXES: tuple[str, ...] = ("//", "*", "/*", "*/")

_JAVA_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"@interface\b"), "annotation"),
    (re.compile(r"\binterface\b"), "interface"),
    (re.compile(r"\benum\b"), "enum"),
    (re.compile(r"\brecord\b"), "record"),
    (re.compile(r"\bclass\b"), "class"),
)

_COMPONENT_DECL_RE = re.compile(
    r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:function|const)\s+([A-Z][A-Za-z0-9_]*)"
)
_JSX_RETURN_RE = re.compile(r"return\s*\(?\s*<[A-Z/a-z]")

_HOOK_RE = re.compile(
    r"(?:^|\n)\s*export\s+(?:default\s+)?(?:function|const)\s+(use[A-Z][A-Za-z0-9_]*)"
)

_JAVA_EXTENSIONS: frozenset[str] = frozenset({".java"})
_WEB_HOOK_EXTENSIONS: frozenset[str] = frozenset({".ts", ".tsx"})
_WEB_COMPONENT_EXTENSIONS: frozenset[str] = frozenset({".tsx"})

_RULE_EXTENSION_MAP: dict[AnnotationRule, frozenset[str]]

_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".zip",
        ".tar",
        ".gz",
        ".jar",
        ".war",
        ".class",
        ".pdf",
        ".exe",
        ".dll",
        ".so",
    }
)


def _build_dispatch_map(
        rules: tuple[AnnotationRule, ...],
) -> tuple[dict[str, tuple[AnnotationRule, ...]], tuple[AnnotationRule, ...]]:
    """Build a suffix-to-rules dispatch table."""
    relevant_suffixes: set[str] = set()
    always_run: list[AnnotationRule] = []

    for rule in rules:
        extensions = _RULE_EXTENSION_MAP.get(rule)
        if extensions is None:
            always_run.append(rule)
        else:
            relevant_suffixes.update(extensions)

    dispatch: dict[str, tuple[AnnotationRule, ...]] = {
        suffix: tuple(
            rule
            for rule in rules
            if (ext := _RULE_EXTENSION_MAP.get(rule)) is None or suffix in ext
        )
        for suffix in relevant_suffixes
    }

    return dispatch, tuple(always_run)


def annotate(nodes: list[Node], profile: EnvironmentProfile) -> list[Node]:
    """Annotate eligible nodes in place."""
    if not profile.annotation_rules:
        return nodes

    dispatch, always_run = _build_dispatch_map(profile.annotation_rules)

    for node in nodes:
        if not _is_eligible(node):
            continue
        _annotate_node(node, dispatch, always_run)

    return nodes


def _is_eligible(node: Node) -> bool:
    return (
            not node.is_dir
            and not node.is_symlink
            and not node.is_collapsed_entry
            and not node.is_summary
    )


def _annotate_node(
        node: Node,
        dispatch: dict[str, tuple[AnnotationRule, ...]],
        always_run: tuple[AnnotationRule, ...],
) -> None:
    suffix = node.path.suffix

    if suffix in _BINARY_EXTENSIONS:
        return

    applicable = dispatch.get(suffix) or always_run
    if not applicable:
        return

    try:
        size = node.path.stat().st_size
    except OSError:
        return

    if size == 0:
        node.annotations.append("empty")
        return

    try:
        content = node.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    for rule in applicable:
        node.annotations.extend(rule(node.path, content))


def _strip_comment_syntax(line: str) -> str:
    stripped = line.strip()
    for marker in ("//", "/*", "*/"):
        if stripped.startswith(marker):
            stripped = stripped[len(marker):].strip()
            break
    if stripped.startswith("*"):
        stripped = stripped[1:].strip()
    return stripped


def java_type_rule(path: Path, content: str) -> list[str]:
    if path.suffix != ".java":
        return []

    for line in content.splitlines():
        searchable = _strip_comment_syntax(line)
        if not searchable:
            continue
        for pattern, label in _JAVA_TYPE_PATTERNS:
            if pattern.search(searchable):
                return [label]

    return []


def java_comment_rule(path: Path, content: str) -> list[str]:
    if path.suffix != ".java":
        return []

    non_blank = [line.strip() for line in content.splitlines() if line.strip()]
    if not non_blank:
        return []

    code_count = sum(
        1 for line in non_blank if not line.startswith(_JAVA_COMMENT_PREFIXES)
    )
    if code_count / len(non_blank) <= ACTIVE_CODE_THRESHOLD:
        return ["commented"]

    return []


def web_component_rule(path: Path, content: str) -> list[str]:
    if path.suffix != ".tsx":
        return []

    if _COMPONENT_DECL_RE.search(content) and _JSX_RETURN_RE.search(content):
        return ["component"]

    return []


def web_hook_rule(path: Path, content: str) -> list[str]:
    if path.suffix not in (".ts", ".tsx"):
        return []

    if _HOOK_RE.search(content):
        return ["hook"]

    return []


_RULE_EXTENSION_MAP = {
    java_type_rule: _JAVA_EXTENSIONS,
    java_comment_rule: _JAVA_EXTENSIONS,
    web_component_rule: _WEB_COMPONENT_EXTENSIONS,
    web_hook_rule: _WEB_HOOK_EXTENSIONS,
}
