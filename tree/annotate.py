"""
Annotation pipeline and rule implementations.

This module is a pure second pass over the node list produced by scan.py.
It does not traverse the filesystem, modify tree structure, or interact with
environment detection. It receives list[Node] and returns list[Node].

Pipeline model
--------------
The annotator owns all file I/O. For each eligible node it:

  1. Checks structural eligibility (ineligible nodes pass through unchanged).
  2. Skips binary extensions without touching the filesystem.
  3. Looks up applicable rules via a precomputed dispatch map (suffix -> rules).
     If no rules apply, the file is not opened.
  4. Stats the file; annotates [empty] immediately if size is zero and stops.
  5. Reads the file content exactly once and passes it to every applicable rule.
  6. Accumulates all returned labels onto node.annotations in rule-declaration order.

Empty-file detection is a pipeline-level pre-rule shortcut, not a rule function.
Profile rule sets contain only content-based classification rules.

Rule contract
-------------
Each rule receives (Path, str) - the file path and its already-read content.
Rules perform only classification logic; they never open files themselves.
Each rule checks its applicable extension as its first operation and returns []
immediately if the file type does not match.

All regex patterns, thresholds, and extension sets are module-level constants
so they can be tuned without reading through function bodies.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from tree.shared_types import AnnotationRule, Node

if TYPE_CHECKING:
    # EnvironmentProfile is only referenced in type annotations at runtime.
    # The TYPE_CHECKING guard breaks the profiles -> annotate -> profiles cycle.
    from tree.profiles import EnvironmentProfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Proportion of non-blank lines that must be comment lines for [commented].
# Heuristic - not a guarantee of full comment coverage.
COMMENT_THRESHOLD: float = 0.8

# Line prefixes that count as comment lines in Java source.
_JAVA_COMMENT_PREFIXES: tuple[str, ...] = ("//", "*", "/*", "*/")

# Compiled patterns for Java type declaration keywords.
# Word-boundary matching prevents false positives from substrings such as
# 'classification', 'recording', or 'enumerate'.
#
# @interface: the '@' is not a word character, so the pattern anchors on the
# right boundary only. The '@' itself provides the left anchor naturally.
#
# Patterns are listed in priority order: @interface must be tested before
# interface to avoid labelling an annotation type as [interface].
_JAVA_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"@interface\b"), "annotation"),
    (re.compile(r"\binterface\b"), "interface"),
    (re.compile(r"\benum\b"), "enum"),
    (re.compile(r"\brecord\b"), "record"),
    (re.compile(r"\bclass\b"), "class"),
)

# Pattern for a React component: function or const with a capitalised identifier
# that also contains a JSX return expression somewhere in the file.
_COMPONENT_DECL_RE = re.compile(
    r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:function|const)\s+([A-Z][A-Za-z0-9_]*)"
)
_JSX_RETURN_RE = re.compile(r"return\s*\(?\s*<[A-Z/a-z]")

# Pattern for a React hook: exported function or const whose name starts with
# 'use' followed by an uppercase letter.
_HOOK_RE = re.compile(
    r"(?:^|\n)\s*export\s+(?:default\s+)?(?:function|const)\s+(use[A-Z][A-Za-z0-9_]*)"
)

# Extensions that each rule applies to. Must stay in sync with the rule functions below.
_JAVA_EXTENSIONS: frozenset[str] = frozenset({".java"})
_WEB_HOOK_EXTENSIONS: frozenset[str] = frozenset({".ts", ".tsx"})
_WEB_COMPONENT_EXTENSIONS: frozenset[str] = frozenset({".tsx"})

# Maps each known rule to the extensions it applies to. Defined at module level
# so it is available to _build_dispatch_map without reconstruction on each call.
# Unknown rules (absent from this map) are conservatively treated as applicable
# to every suffix - they are included in every known suffix entry and used as
# the fallback for unknown suffixes in the dispatch map.
# Forward references are resolved at module load time after all rule functions
# are defined; see the assignment at the bottom of this module.
_RULE_EXTENSION_MAP: dict[AnnotationRule, frozenset[str]]

# File extensions whose content is binary or non-text; never opened for annotation.
_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".jar", ".war", ".class",
    ".pdf", ".exe", ".dll", ".so",
})


# ---------------------------------------------------------------------------
# Dispatch map construction
# ---------------------------------------------------------------------------

def _build_dispatch_map(
        rules: tuple[AnnotationRule, ...],
) -> tuple[dict[str, tuple[AnnotationRule, ...]], tuple[AnnotationRule, ...]]:
    """
    Precompute a suffix -> applicable rules mapping for the given rule set.

    Returns two values:
      dispatch   - maps each file suffix to the ordered tuple of rules that can
                   produce output for it. Declaration order from profile.annotation_rules
                   is preserved exactly within every suffix entry.
      always_run - rules absent from _RULE_EXTENSION_MAP; these are conservatively
                   treated as applicable to every suffix and serve as the fallback
                   for suffixes not present in the dispatch map.

    Construction is O(R * S) where R is the number of rules and S is the number
    of distinct suffixes covered by those rules - both negligibly small in practice.
    The map is built once per annotate() call and reused for every eligible node.

    Declaration order guarantee
    ---------------------------
    Building per-suffix lists by grouping rules and then merging would place all
    unknown rules after all known rules, violating original order when unknown and
    known rules are interleaved in the profile. Instead, construction proceeds in
    two passes:

      Pass 1 - collect the set of relevant suffixes and identify unknown rules.
      Pass 2 - for each suffix, iterate rules once in declaration order, including
               a rule iff it is unknown OR its extension set contains that suffix.

    This is equivalent to what the previous per-file filter produced, but the work
    is done once rather than once per file.
    """
    # Pass 1: collect all suffixes that at least one known rule covers, and
    # identify which rules are unknown (absent from _RULE_EXTENSION_MAP).
    relevant_suffixes: set[str] = set()
    always_run: list[AnnotationRule] = []

    for rule in rules:
        extensions = _RULE_EXTENSION_MAP.get(rule)
        if extensions is None:
            always_run.append(rule)
        else:
            relevant_suffixes.update(extensions)

    # Pass 2: for each relevant suffix, walk rules in declaration order and
    # include the rule if it applies to that suffix or is an unknown rule.
    # This is the only construction path that guarantees original order is
    # preserved when known and unknown rules are interleaved.
    dispatch: dict[str, tuple[AnnotationRule, ...]] = {
        suffix: tuple(
            rule for rule in rules
            if (ext := _RULE_EXTENSION_MAP.get(rule)) is None or suffix in ext
        )
        for suffix in relevant_suffixes
    }

    return dispatch, tuple(always_run)


# ---------------------------------------------------------------------------
# Annotation pipeline
# ---------------------------------------------------------------------------

def annotate(nodes: list[Node], profile: EnvironmentProfile) -> list[Node]:
    """
    Apply profile annotation rules to all eligible nodes in-place.

    Eligible nodes: regular files that are not symlinks, collapsed entries,
    or summary nodes. All other nodes pass through unchanged.

    Builds a dispatch map once before iterating nodes so that per-file rule
    selection is a single dict lookup rather than a filtered scan of all rules.

    Returns the same list with annotations populated where applicable.
    """
    if not profile.annotation_rules:
        return nodes

    dispatch, always_run = _build_dispatch_map(profile.annotation_rules)

    for node in nodes:
        if not _is_eligible(node):
            continue
        _annotate_node(node, dispatch, always_run)

    return nodes


def _is_eligible(node: Node) -> bool:
    """Return True only if a node should be considered for annotation."""
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
    """
    Run applicable rules against a single eligible node, accumulating annotations.

    Extension-based filtering happens before any filesystem access:
      - Binary extensions are skipped immediately.
      - Applicable rules are resolved via a single dict lookup into the precomputed
        dispatch map. If the suffix is absent from the map, always_run rules are used
        as the fallback (these are rules not registered in _RULE_EXTENSION_MAP).
      - If no rules apply, the file is not opened.

    Empty-file detection is a pipeline-level shortcut: if the file is zero bytes,
    [empty] is recorded and no rules run. This avoids reading empty files and
    keeps rule functions free of empty-content handling.

    If the file cannot be read (stat or open failure), annotation is skipped
    silently - one unreadable file must never abort the entire run.
    """
    suffix = node.path.suffix

    if suffix in _BINARY_EXTENSIONS:
        return

    # Single dict lookup replaces the per-file rule filter loop.
    # Falls back to always_run for suffixes absent from the dispatch map,
    # ensuring unknown rules (not in _RULE_EXTENSION_MAP) still fire.
    applicable = dispatch.get(suffix) or always_run
    if not applicable:
        return

    try:
        size = node.path.stat().st_size
    except OSError:
        return

    # Pipeline-level empty shortcut: annotate [empty] without reading content.
    # Rule functions are not involved - this is environment-independent behaviour.
    if size == 0:
        node.annotations.append("empty")
        return

    # Read the file exactly once; pass content to every applicable rule.
    try:
        content = node.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    for rule in applicable:
        node.annotations.extend(rule(node.path, content))


# ---------------------------------------------------------------------------
# Java annotation rules
# ---------------------------------------------------------------------------

def _strip_comment_syntax(line: str) -> str:
    """
    Remove comment-marker syntax from a single line, returning the underlying text.

    Strips leading //, /*, */, and * markers so that declaration keywords written
    inside comments are still visible to keyword searches. Blank lines and
    lines that are pure punctuation (e.g. a bare '*') become empty strings.
    """
    stripped = line.strip()
    for marker in ("//", "/*", "*/"):
        if stripped.startswith(marker):
            stripped = stripped[len(marker):].strip()
            break
    # Handle ' * text' style Javadoc continuation lines.
    if stripped.startswith("*"):
        stripped = stripped[1:].strip()
    return stripped


def java_type_rule(path: Path, content: str) -> list[str]:
    """
    Identify the primary Java type declaration in a .java file.

    Searches all non-blank lines for a declaration keyword, including lines
    that are inside comments. Comment syntax markers are stripped from each
    line before the keyword search so that declarations such as:

        // public interface Example {}
        /* public record Point(...) {} */

    are detected correctly. This allows a fully-commented file to receive
    both a type label (e.g. [interface]) and [commented] from java_comment_rule.

    Returns one of: [class], [interface], [enum], [record], [annotation].
    Returns [] if no declaration is found or the file is not a .java file.
    """
    if path.suffix != ".java":
        return []

    for line in content.splitlines():
        searchable = _strip_comment_syntax(line)
        if not searchable:
            continue
        # @interface pattern is tested before interface to avoid a false match
        # on annotation types - both patterns would match otherwise.
        for pattern, label in _JAVA_TYPE_PATTERNS:
            if pattern.search(searchable):
                return [label]

    return []


def java_comment_rule(path: Path, content: str) -> list[str]:
    """
    Return [commented] if the file appears to be predominantly commented.

    Strips blank lines, then checks whether the proportion of comment lines
    meets or exceeds COMMENT_THRESHOLD. Heuristic only - not a guarantee of
    full comment coverage.

    This rule is independent of java_type_rule. A file may receive [commented]
    together with a type label such as [interface] if the comment ratio is
    met and a declaration keyword is also present.

    Returns [] if the file is not a .java file or the threshold is not met.
    """
    if path.suffix != ".java":
        return []

    non_blank = [line.strip() for line in content.splitlines() if line.strip()]
    if not non_blank:
        return []

    comment_count = sum(
        1 for line in non_blank if line.startswith(_JAVA_COMMENT_PREFIXES)
    )
    if comment_count / len(non_blank) >= COMMENT_THRESHOLD:
        return ["commented"]

    return []


# ---------------------------------------------------------------------------
# Web annotation rules
# ---------------------------------------------------------------------------

def web_component_rule(path: Path, content: str) -> list[str]:
    """
    Return [component] if the .tsx file appears to define a React component.

    Heuristic: the file declares a function or const with a capitalised
    identifier AND contains a JSX return expression. Conservative - avoids
    false positives from utility files that happen to export capitalised names.

    Returns [] if the file is not a .tsx file or the pattern is not matched.
    """
    if path.suffix != ".tsx":
        return []

    if _COMPONENT_DECL_RE.search(content) and _JSX_RETURN_RE.search(content):
        return ["component"]

    return []


def web_hook_rule(path: Path, content: str) -> list[str]:
    """
    Return [hook] if the .ts or .tsx file appears to export a React hook.

    Heuristic: the file exports a function or const whose name begins with
    'use' followed by an uppercase letter.

    Returns [] if the file extension does not match or the pattern is absent.
    """
    if path.suffix not in (".ts", ".tsx"):
        return []

    if _HOOK_RE.search(content):
        return ["hook"]

    return []


# ---------------------------------------------------------------------------
# Rule-to-extension map (assigned after rule functions are defined)
# ---------------------------------------------------------------------------

# Populated here rather than at the declaration site because the rule
# functions must exist before they can be used as dict keys.
_RULE_EXTENSION_MAP = {
    java_type_rule: _JAVA_EXTENSIONS,
    java_comment_rule: _JAVA_EXTENSIONS,
    web_component_rule: _WEB_COMPONENT_EXTENSIONS,
    web_hook_rule: _WEB_HOOK_EXTENSIONS,
}
