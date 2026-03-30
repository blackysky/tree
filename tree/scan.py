"""
Directory traversal and node construction.

This module is entirely environment-agnostic. All environment-specific behaviour
enters through the EnvironmentProfile. The profile determines which directories
are excluded, which are collapsed, and which file extensions are included.

Symlinks are never followed. A symlink to a directory is recorded as a leaf node
and never descended into. A symlink to a file is recorded as a visible node.

Output is deterministic: only the filenames that would produce a node are
collected, and that retained subset is sorted before emission. Directory
entries are sorted before any filtering or inclusion decision is made.

Parent-before-child ordering is guaranteed: a directory node is always emitted
before any of its children appear in the output list.
"""

from __future__ import annotations

import heapq
import os
from pathlib import Path

from tree.profiles import EnvironmentProfile
from tree.shared_types import Node

# Maximum number of entries shown inside a collapsed directory before a summary
# node is emitted. This is a display cap - only this many entries are retained
# in memory regardless of total directory size.
COLLAPSED_DIR_DISPLAY_CAP: int = 20


def scan(
        root: Path,
        profile: EnvironmentProfile,
        output_path: Path,
        extra_exclusions: frozenset[str],
) -> list[Node]:
    """
    Traverse root and return an ordered list of Node objects.

    Directories in profile.excluded_dirs or extra_exclusions are pruned entirely.
    Directories in profile.collapsed_dirs are scanned shallowly via scan_collapsed.
    Symlink directories are recorded as leaf nodes and never descended into.
    The output file itself is excluded from results regardless of where it lives.

    Traversal order is lexicographic at every level, guaranteed deterministic.
    Parent-before-child ordering is guaranteed throughout the output list.
    """
    resolved_output = output_path.resolve()
    all_excluded = profile.excluded_dirs | extra_exclusions
    nodes: list[Node] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)

        # Sort in-place before any mutation so traversal order is deterministic.
        dirnames.sort()

        # Emit the current directory node before any of its children so that
        # parent-before-child ordering is guaranteed throughout the output list.
        # The root itself is not emitted - it is rendered as the tree header.
        if depth > 0:
            nodes.append(Node(path=current, depth=depth, is_dir=True))

        # Classify each subdirectory. Build the keep list explicitly rather than
        # removing entries one by one to avoid index-shifting bugs.
        keep: list[str] = []

        for name in dirnames:
            child = current / name

            if child.resolve() == resolved_output:
                # The output path happens to be a directory - exclude silently.
                continue

            if os.path.islink(child):
                # Record symlink directories as leaf nodes; never descend.
                nodes.append(Node(
                    path=child,
                    depth=depth + 1,
                    is_dir=True,
                    is_symlink=True,
                ))
                continue

            if name in all_excluded:
                continue

            if name in profile.collapsed_dirs:
                # Emit the collapsed directory node before its shallow contents.
                nodes.append(Node(path=child, depth=depth + 1, is_dir=True))
                nodes.extend(scan_collapsed(child, depth=depth + 1))
                continue

            keep.append(name)

        # Replace dirnames in-place so os.walk descends only into kept directories.
        dirnames[:] = keep

        # Filter filenames before sorting: collect only those that would produce a
        # node, then sort the retained subset. In noisy directories (e.g. a build
        # output or assets folder full of generated files) this avoids sorting
        # entries that the profile would discard immediately afterward.
        #
        # Output-path exclusion is checked first so that a symlink pointing at the
        # output file is still excluded correctly. The is_symlink flag is captured
        # here and reused at node construction to avoid a redundant syscall.
        retained: list[tuple[str, Path, bool]] = []
        for name in filenames:
            child = current / name

            if child.resolve() == resolved_output:
                continue

            is_symlink = os.path.islink(child)

            # Symlink files are structural facts in the tree, not content files.
            # They are retained unconditionally - their visibility must not depend
            # on whether the symlink filename happens to satisfy extension filters.
            # This mirrors the treatment of symlink directories above.
            if not is_symlink:
                if name not in profile.special_files and child.suffix not in profile.extensions:
                    continue

            retained.append((name, child, is_symlink))

        for name, child, is_symlink in sorted(retained):
            nodes.append(Node(
                path=child,
                depth=depth + 1,
                is_dir=False,
                is_symlink=is_symlink,
            ))

    return nodes


def scan_collapsed(dir_path: Path, depth: int) -> list[Node]:
    """
    Shallow-scan a collapsed directory, returning at most COLLAPSED_DIR_DISPLAY_CAP
    entry nodes plus an optional summary node.

    Memory is bounded independently of total directory size. The directory is
    enumerated exactly once: a bounded max-heap retains the CAP lexicographically
    smallest entries while a running counter tracks the total.

    Heap strategy
    -------------
    To keep the N smallest strings from a stream with bounded memory, a max-heap
    of size CAP is maintained: when full and a smaller entry arrives, the largest
    is evicted. Python's heapq is a min-heap; a max-heap over strings is obtained
    by negating the key via _NegStr, which reverses string comparison order without
    altering the underlying value. heapreplace atomically pops the heap minimum
    (the largest name under negation) and pushes the new entry.

    After the pass, retained entries are sorted ascending by name to restore
    lexicographic display order before Node construction.
    """
    heap: list[tuple[_NegStr, os.DirEntry[str]]] = []
    total = 0

    try:
        scanner = os.scandir(dir_path)
    except OSError:
        return []

    with scanner:
        for entry in scanner:
            total += 1
            item = (_NegStr(entry.name), entry)
            if len(heap) < COLLAPSED_DIR_DISPLAY_CAP:
                heapq.heappush(heap, item)
            elif entry.name < -heap[0][0]:
                # Current entry is lexicographically smaller than the largest
                # retained entry; evict the largest and retain this one instead.
                heapq.heapreplace(heap, item)

    # Restore ascending lexicographic order for deterministic display.
    retained = sorted((entry for _, entry in heap), key=lambda e: e.name)

    nodes: list[Node] = []

    for entry in retained:
        nodes.append(Node(
            path=Path(entry.path),
            depth=depth + 1,
            is_dir=entry.is_dir(follow_symlinks=False),
            is_symlink=entry.is_symlink(),
            is_collapsed_entry=True,
        ))

    remainder = total - COLLAPSED_DIR_DISPLAY_CAP
    if remainder > 0:
        nodes.append(Node(
            path=dir_path,
            depth=depth + 1,
            is_dir=False,
            is_summary=True,
            summary_label=f"… {remainder} more entries",
        ))

    return nodes


class _NegStr:
    """
    Wrapper that reverses string comparison order.

    Used to simulate a max-heap over strings with Python's min-heap (heapq).
    Storing _NegStr(name) instead of name causes heapq to treat the
    lexicographically largest string as the heap minimum, making it the first
    candidate for eviction when the heap is at capacity.

    Negation (-obj) returns the unwrapped string, mirroring integer negation
    semantics and allowing the eviction guard (entry.name < -heap[0][0]) to
    compare a plain string against the current heap maximum without unwrapping
    manually.
    """

    __slots__ = ("_s",)

    def __init__(self, s: str) -> None:
        self._s = s

    def __neg__(self) -> str:
        return self._s

    def __lt__(self, other: _NegStr) -> bool:
        return self._s > other._s  # reversed

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _NegStr) and self._s == other._s

    def __le__(self, other: _NegStr) -> bool:
        return self._s >= other._s  # reversed
