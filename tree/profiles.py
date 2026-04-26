"""Environment profiles."""

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
    """Environment settings."""

    name: str
    extensions: frozenset[str]
    special_files: frozenset[str]
    excluded_dirs: frozenset[str]
    collapsed_dirs: frozenset[str]
    annotation_rules: tuple[AnnotationRule, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        overlap = self.excluded_dirs & self.collapsed_dirs
        if overlap:
            raise ValueError(
                f"Profile '{self.name}': directories appear in both excluded_dirs and "
                f"collapsed_dirs: {sorted(overlap)}"
            )


JAVA_PROFILE = EnvironmentProfile(
    name="Java",
    extensions=frozenset({".java", ".sql", ".properties", ".yaml", ".yml"}),
    special_files=frozenset({"pom.xml"}),
    excluded_dirs=frozenset(
        {
            "target",
            ".mvn",
            ".git",
            ".idea",
            ".vscode",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            ".tox",
        }
    ),
    collapsed_dirs=frozenset(),
    annotation_rules=(java_type_rule, java_comment_rule),
)

WEB_PROFILE = EnvironmentProfile(
    name="Web",
    extensions=frozenset(
        {
            ".tsx",
            ".ts",
            ".html",
            ".css",
            ".js",
            ".png",
            ".svg",
            ".json",
            ".md",
        }
    ),
    special_files=frozenset({"package.json", "tsconfig.json"}),
    excluded_dirs=frozenset(
        {
            ".next",
            "dist",
            "build",
            ".nuxt",
            ".cache",
            ".git",
            ".idea",
            ".vscode",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            ".tox",
        }
    ),
    collapsed_dirs=frozenset({"node_modules"}),
    annotation_rules=(web_component_rule, web_hook_rule),
)

UNKNOWN_PROFILE = EnvironmentProfile(
    name="Unknown",
    extensions=frozenset(
        {
            ".py",
            ".js",
            ".ts",
            ".java",
            ".md",
            ".txt",
            ".yml",
            ".yaml",
            ".json",
        }
    ),
    special_files=frozenset(),
    excluded_dirs=frozenset(
        {
            ".git",
            ".idea",
            ".vscode",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            "node_modules",
            "target",
            "dist",
            "build",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            ".tox",
        }
    ),
    collapsed_dirs=frozenset(),
    annotation_rules=(),
)
