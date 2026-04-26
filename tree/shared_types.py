"""Shared primitive types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

AnnotationRule = Callable[[Path, str], list[str]]


@dataclass
class Node:
    """A scanned filesystem entry."""

    path: Path
    depth: int
    is_dir: bool
    is_symlink: bool = False
    is_collapsed_entry: bool = False
    is_summary: bool = False
    summary_label: str = ""
    annotations: list[str] = field(default_factory=list)
