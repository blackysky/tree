"""
Environment profiles - the single source of truth for all environment-specific rules.

Each profile is a self-contained, fully self-describing constant. No profile inherits
from another, and no shared global sets exist. Every profile explicitly declares its own
excluded directories so that it remains correct in isolation.

Import structure:
  profiles.py  imports concrete rule functions directly from annotate.py.
  annotate.py  imports AnnotationRule and Node from shared_types at runtime;
               it references EnvironmentProfile only under TYPE_CHECKING,
               so it does not import profiles.py at runtime.

This means profiles.py -> annotate.py is a real runtime import, but
annotate.py -> profiles.py is type-checker-only, keeping the graph acyclic.
tree_cli.py performs no rule injection; profiles are fully assembled at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tree.annotate import (
    java_comment_rule,
    java_type_rule,
    web_component_rule,
    web_hook_rule,
)
from tree.shared_types import AnnotationRule


@dataclass(frozen=True)
class EnvironmentProfile:
    """
    Immutable description of a development environment.

    Drives all environment-specific behaviour in scan, annotate, and render.
    Adding a new environment means adding a new constant here - nothing else changes
    in scan.py or render.py.
    """

    name: str
    extensions: frozenset[str]
    special_files: frozenset[str]
    excluded_dirs: frozenset[str]
    collapsed_dirs: frozenset[str]
    annotation_rules: tuple[AnnotationRule, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Enforce the architecture invariant: a directory is either excluded or
        # collapsed - never both. Checked at construction time, not at runtime.
        overlap = self.excluded_dirs & self.collapsed_dirs
        if overlap:
            raise ValueError(
                f"Profile '{self.name}': directories appear in both excluded_dirs and "
                f"collapsed_dirs: {sorted(overlap)}"
            )


# ---------------------------------------------------------------------------
# Profile constants
# ---------------------------------------------------------------------------

JAVA_PROFILE = EnvironmentProfile(
    name="Java",
    extensions=frozenset({".java", ".sql", ".properties", ".yaml", ".yml"}),
    special_files=frozenset({"pom.xml"}),
    excluded_dirs=frozenset({
        "target", ".mvn", ".git", ".idea", ".vscode",
        "__pycache__", ".venv", "venv", "env",
        ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
    }),
    collapsed_dirs=frozenset(),
    annotation_rules=(java_type_rule, java_comment_rule),
)

WEB_PROFILE = EnvironmentProfile(
    name="Web",
    extensions=frozenset({
        ".tsx", ".ts", ".html", ".css", ".js",
        ".png", ".svg", ".json", ".md",
    }),
    special_files=frozenset({"package.json", "tsconfig.json"}),
    excluded_dirs=frozenset({
        ".next", "dist", "build", ".nuxt", ".cache",
        ".git", ".idea", ".vscode",
        "__pycache__", ".venv", "venv", "env",
        ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
    }),
    collapsed_dirs=frozenset({"node_modules"}),
    annotation_rules=(web_component_rule, web_hook_rule),
)

# node_modules is excluded entirely here - without environment context its
# presence is noise rather than signal.
UNKNOWN_PROFILE = EnvironmentProfile(
    name="Unknown",
    extensions=frozenset({
        ".py", ".js", ".ts", ".java", ".md", ".txt",
        ".yml", ".yaml", ".json",
    }),
    special_files=frozenset(),
    excluded_dirs=frozenset({
        ".git", ".idea", ".vscode",
        "__pycache__", ".venv", "venv", "env",
        "node_modules", "target", "dist", "build",
        ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
    }),
    collapsed_dirs=frozenset(),
    annotation_rules=(),
)
