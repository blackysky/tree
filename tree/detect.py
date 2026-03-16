"""
Heuristic environment detection.

Detection is evidence-based: a fixed list of named clues is evaluated against the
project root, each contributing a weighted score to one environment. The decision
function converts accumulated scores into a result with an explicit confidence level.

Ambiguity is never resolved by tie-breaking - it is surfaced explicitly so the user
can resolve it with --env if needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from tree.config import Confidence, Environment

# The gap by which one environment's score must exceed another to be considered
# confident. If the gap is below this threshold the result is LOW confidence.
CONFIDENCE_GAP: int = 2


# ---------------------------------------------------------------------------
# Internal clue structure
# ---------------------------------------------------------------------------

class _Clue(NamedTuple):
    description: str
    environment: Environment
    weight: int


def _check_file_at_root(root: Path, filename: str) -> bool:
    return (root / filename).is_file()


def _check_dir_at_root(root: Path, dirname: str) -> bool:
    return (root / dirname).is_dir()


def _has_extension_shallow(root: Path, suffix: str) -> bool:
    """Return True if any file with the given suffix exists at root or one level deep.

    Unreadable directories (e.g. ~/.Trash, system volumes, protected folders) are
    silently skipped. Detection continues with whatever paths are accessible.
    """
    try:
        entries = list(root.iterdir())
    except PermissionError:
        return False

    for entry in entries:
        if entry.is_file() and entry.suffix == suffix:
            return True
        if entry.is_dir() and not entry.is_symlink():
            try:
                for child in entry.iterdir():
                    if child.is_file() and child.suffix == suffix:
                        return True
            except PermissionError:
                continue

    return False


# ---------------------------------------------------------------------------
# Clue evaluators
# Each returns a _Clue if the evidence is present, None otherwise.
# The list is the authoritative registry - tunable without touching control flow.
# ---------------------------------------------------------------------------

def _clue_pom_xml(root: Path) -> _Clue | None:
    if _check_file_at_root(root, "pom.xml"):
        return _Clue("pom.xml present at root", Environment.JAVA, 3)
    return None


def _clue_gradle(root: Path) -> _Clue | None:
    if _check_file_at_root(root, "build.gradle") or _check_file_at_root(root, "build.gradle.kts"):
        return _Clue("build.gradle / build.gradle.kts present at root", Environment.JAVA, 3)
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
        return _Clue(".tsx / .ts files found at root or one level deep", Environment.WEB, 2)
    return None


# Ordered list of all clue evaluators. Add new clues here when extending environments.
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


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectionResult:
    """
    Outcome of heuristic environment detection.

    Retained in Config for use in the output header and for diagnostics.
    Confidence reflects how decisive the evidence was, not how correct the result is.
    """

    environment: Environment
    confidence: Confidence
    java_score: int
    web_score: int
    clues_matched: tuple[str, ...]


# ---------------------------------------------------------------------------
# Detection entry point
# ---------------------------------------------------------------------------

def detect(root: Path) -> DetectionResult:
    """
    Evaluate all clues against the given root directory and return a DetectionResult.

    Never breaks ties by picking arbitrarily - ambiguity is always reported as UNKNOWN
    with LOW confidence so the caller can decide (e.g. prompt the user to pass --env).
    """
    java_score = 0
    web_score = 0
    matched: list[str] = []

    for evaluator in _CLUES:
        clue = evaluator(root)
        if clue is None:
            continue
        matched.append(clue.description)
        if clue.environment is Environment.JAVA:
            java_score += clue.weight
        elif clue.environment is Environment.WEB:
            web_score += clue.weight

    return _decide(java_score, web_score, matched)


def _decide(java_score: int, web_score: int, matched: list[str]) -> DetectionResult:
    """Convert accumulated scores into a result with an explicit confidence level."""
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

    # Scores are equal, or the gap is below the confidence threshold.
    # Ambiguity is surfaced explicitly - no arbitrary tie-breaking.
    return DetectionResult(
        environment=Environment.UNKNOWN,
        confidence=Confidence.LOW,
        java_score=java_score,
        web_score=web_score,
        clues_matched=tuple(matched),
    )
