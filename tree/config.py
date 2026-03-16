"""
Core configuration types for the Tree tool.

Contains only data definitions - no logic, no I/O, no filesystem access.

Config is constructed once in tree.py and flows through the entire pipeline
unchanged. No downstream module mutates it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from tree.profiles import EnvironmentProfile

if TYPE_CHECKING:
    # Imported for type annotations only. At runtime this import is skipped,
    # which breaks the circular dependency: detect.py imports config.py for
    # Environment and Confidence; config.py references DetectionResult only
    # in type annotations, so no runtime import of detect.py occurs here.
    from tree.detect import DetectionResult


class Environment(Enum):
    JAVA = auto()
    WEB = auto()
    UNKNOWN = auto()


class Confidence(Enum):
    CONFIDENT = auto()
    LOW = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class Config:
    """
    Immutable configuration object constructed once and passed through the pipeline.

    All path fields are resolved absolute paths. No field is derived or computed
    after construction - callers are responsible for resolving paths before passing
    them in.
    """

    root: Path
    profile: EnvironmentProfile
    output_path: Path
    use_ascii: bool
    extra_exclusions: frozenset[str]
    env_overridden: bool
    detection_result: DetectionResult
