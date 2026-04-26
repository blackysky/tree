"""Directory traversal and node construction."""

from __future__ import annotations

import heapq
import os
from pathlib import Path

from tree.profiles import EnvironmentProfile
from tree.shared_types import Node

COLLAPSED_DIR_DISPLAY_CAP: int = 20


def scan(
        root: Path,
        profile: EnvironmentProfile,
        output_path: Path,
        extra_exclusions: frozenset[str],
) -> list[Node]:
    """Scan root and return nodes in display order."""
    resolved_output = output_path.resolve()
    all_excluded = profile.excluded_dirs | extra_exclusions
    nodes: list[Node] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)

        dirnames.sort()

        if depth > 0:
            nodes.append(Node(path=current, depth=depth, is_dir=True))

        keep: list[str] = []

        for name in dirnames:
            child = current / name

            if child.resolve() == resolved_output:
                continue

            if os.path.islink(child):
                nodes.append(
                    Node(
                        path=child,
                        depth=depth + 1,
                        is_dir=True,
                        is_symlink=True,
                    )
                )
                continue

            if name in all_excluded:
                continue

            if name in profile.collapsed_dirs:
                nodes.append(Node(path=child, depth=depth + 1, is_dir=True))
                nodes.extend(scan_collapsed(child, depth=depth + 1))
                continue

            keep.append(name)

        dirnames[:] = keep

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
                if (
                        name not in profile.special_files
                        and child.suffix not in profile.extensions
                ):
                    continue

            retained.append((name, child, is_symlink))

        for name, child, is_symlink in sorted(retained):
            nodes.append(
                Node(
                    path=child,
                    depth=depth + 1,
                    is_dir=False,
                    is_symlink=is_symlink,
                )
            )

    return nodes


def scan_collapsed(dir_path: Path, depth: int) -> list[Node]:
    """Return a shallow listing for a collapsed directory."""
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
                heapq.heapreplace(heap, item)

    retained = sorted((entry for _, entry in heap), key=lambda e: e.name)

    nodes: list[Node] = []

    for entry in retained:
        nodes.append(
            Node(
                path=Path(entry.path),
                depth=depth + 1,
                is_dir=entry.is_dir(follow_symlinks=False),
                is_symlink=entry.is_symlink(),
                is_collapsed_entry=True,
            )
        )

    remainder = total - COLLAPSED_DIR_DISPLAY_CAP
    if remainder > 0:
        nodes.append(
            Node(
                path=dir_path,
                depth=depth + 1,
                is_dir=False,
                is_summary=True,
                summary_label=f"… {remainder} more entries",
            )
        )

    return nodes


class _NegStr:
    """Reverse string ordering for the collapsed-directory heap."""

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
