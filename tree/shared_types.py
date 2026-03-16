"""
Shared primitive types with no dependencies on any other tree module.

Placing Node and AnnotationRule here breaks what would otherwise be a circular
import: profiles.py imports annotate.py for rule functions, and annotate.py
needs both types without importing profiles.py at runtime.

Runtime import graph:

    shared_types   <-- annotate.py  (imports AnnotationRule, Node)
    shared_types   <-- scan.py      (imports Node)
    shared_types   <-- profiles.py  (imports AnnotationRule)
    annotate.py    <-- profiles.py  (imports rule functions)

annotate.py references EnvironmentProfile only under TYPE_CHECKING - it is
not imported at runtime, keeping the graph acyclic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# An annotation rule: accepts a file path and its already-read text content,
# returns zero or more annotation label strings.
#
# The annotator owns all file I/O - it reads the file once and passes the
# content to every applicable rule. Rules perform only classification logic;
# they never open files themselves.
#
# Must not mutate state or depend on external configuration.
AnnotationRule = Callable[[Path, str], list[str]]


@dataclass
class Node:
    """
    Represents a single filesystem entry in the scan output.

    This is a data container only. It carries structural facts about one entry.
    Annotation labels are populated by annotate.py after the scan is complete.

    Fields set during scan:
        path, depth, is_dir, is_symlink, is_collapsed_entry, is_summary, summary_label

    Fields populated later by annotate.py:
        annotations
    """

    path: Path
    depth: int
    is_dir: bool
    is_symlink: bool = False
    is_collapsed_entry: bool = False
    is_summary: bool = False
    summary_label: str = ""
    annotations: list[str] = field(default_factory=list)
