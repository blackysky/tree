"""Heuristic environment detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from tree.config import Confidence, Environment

CONFIDENCE_GAP: int = 2


class _Clue(NamedTuple):
    description: str
    environment: Environment
    weight: int


def _check_file_at_root(root: Path, filename: str) -> bool:
    return (root / filename).is_file()


def _check_dir_at_root(root: Path, dirname: str) -> bool:
    return (root / dirname).is_dir()


def _has_extension_shallow(root: Path, suffix: str) -> bool:
    """Check for a suffix at root or one level down."""
    try:
        entries = list(root.iterdir())
    except OSError:
        return False

    for entry in entries:
        if entry.is_file() and entry.suffix == suffix:
            return True
        if entry.is_dir() and not entry.is_symlink():
            try:
                for child in entry.iterdir():
                    if child.is_file() and child.suffix == suffix:
                        return True
            except OSError:
                continue

    return False


def _clue_pom_xml(root: Path) -> _Clue | None:
    if _check_file_at_root(root, "pom.xml"):
        return _Clue("pom.xml present at root", Environment.JAVA, 3)
    return None


def _clue_gradle(root: Path) -> _Clue | None:
    if _check_file_at_root(root, "build.gradle") or _check_file_at_root(
        root, "build.gradle.kts"
    ):
        return _Clue(
            "build.gradle / build.gradle.kts present at root", Environment.JAVA, 3
        )
    return None


def _clue_src_main_java(root: Path) -> _Clue | None:
    if (root / "src" / "main" / "java").is_dir():
        return _Clue("src/main/java path exists", Environment.JAVA, 2)
    return None


def _clue_java_files(root: Path) -> _Clue | None:
    if _has_extension_shallow(root, ".java"):
        return _Clue(".java files found at root or one level deep", Environment.JAVA, 2)
    return None


def _clue_package_json(root: Path) -> _Clue | None:
    if _check_file_at_root(root, "package.json"):
        return _Clue("package.json present at root", Environment.WEB, 3)
    return None


def _clue_tsconfig_json(root: Path) -> _Clue | None:
    if _check_file_at_root(root, "tsconfig.json"):
        return _Clue("tsconfig.json present at root", Environment.WEB, 2)
    return None


def _clue_node_modules(root: Path) -> _Clue | None:
    if _check_dir_at_root(root, "node_modules"):
        return _Clue("node_modules/ directory present at root", Environment.WEB, 1)
    return None


def _clue_ts_tsx_files(root: Path) -> _Clue | None:
    if _has_extension_shallow(root, ".tsx") or _has_extension_shallow(root, ".ts"):
        return _Clue(
            ".tsx / .ts files found at root or one level deep", Environment.WEB, 2
        )
    return None


# Ordered list of all clue evaluators.
_CLUES = (
    _clue_pom_xml,
    _clue_gradle,
    _clue_src_main_java,
    _clue_java_files,
    _clue_package_json,
    _clue_tsconfig_json,
    _clue_node_modules,
    _clue_ts_tsx_files,
)


@dataclass(frozen=True)
class DetectionResult:
    """Detection result."""

    environment: Environment
    confidence: Confidence
    java_score: int
    web_score: int
    clues_matched: tuple[str, ...]


def detect(root: Path) -> DetectionResult:
    """Detect the most likely environment for root."""
    scores: dict[Environment, int] = {
        Environment.JAVA: 0,
        Environment.WEB: 0,
    }
    matched: list[str] = []

    for evaluator in _CLUES:
        clue = evaluator(root)
        if clue is None:
            continue
        matched.append(clue.description)
        if clue.environment not in scores:
            raise ValueError(
                f"Unsupported clue environment in detection: {clue.environment!r}. "
                "Update detect() and _decide() to handle this environment."
            )
        scores[clue.environment] += clue.weight

    return _decide(
        java_score=scores[Environment.JAVA],
        web_score=scores[Environment.WEB],
        matched=matched,
    )


def _decide(java_score: int, web_score: int, matched: list[str]) -> DetectionResult:
    """Turn scores into a detection result."""
    if java_score == 0 and web_score == 0:
        return DetectionResult(
            environment=Environment.UNKNOWN,
            confidence=Confidence.UNKNOWN,
            java_score=0,
            web_score=0,
            clues_matched=tuple(matched),
        )

    gap = abs(java_score - web_score)

    if gap >= CONFIDENCE_GAP and java_score > web_score:
        return DetectionResult(
            environment=Environment.JAVA,
            confidence=Confidence.CONFIDENT,
            java_score=java_score,
            web_score=web_score,
            clues_matched=tuple(matched),
        )

    if gap >= CONFIDENCE_GAP and web_score > java_score:
        return DetectionResult(
            environment=Environment.WEB,
            confidence=Confidence.CONFIDENT,
            java_score=java_score,
            web_score=web_score,
            clues_matched=tuple(matched),
        )

    return DetectionResult(
        environment=Environment.UNKNOWN,
        confidence=Confidence.LOW,
        java_score=java_score,
        web_score=web_score,
        clues_matched=tuple(matched),
    )
