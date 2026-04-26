"""Core configuration types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from tree.profiles import EnvironmentProfile

if TYPE_CHECKING:
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
    """Immutable pipeline config."""

    root: Path
    profile: EnvironmentProfile
    output_path: Path
    use_ascii: bool
    extra_exclusions: frozenset[str]
    env_overridden: bool
    detection_result: DetectionResult
