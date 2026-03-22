"""
Tree - CLI entry point and orchestration layer.

This file is intentionally thin. All non-trivial logic lives in the modules
under tree/. This file resolves arguments, selects a profile, constructs
Config, and calls the pipeline in sequence.

Usage:
    python tree_cli.py [--root PATH] [--env {java,web}] [--output PATH]
                   [--ascii] [--exclude DIR] [--debug-detect]
                   [--no-node-modules] [--json]
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from tree.annotate import annotate
from tree.config import Confidence, Config, Environment
from tree.detect import DetectionResult, detect
from tree.profiles import (
    EnvironmentProfile,
    JAVA_PROFILE,
    UNKNOWN_PROFILE,
    WEB_PROFILE,
)
from tree.render import render_json, render_text, write_output
from tree.scan import scan


def main() -> None:
    args = _parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"Error: root path does not exist or is not a directory: {root}")

    default_filename = "Structure.json" if args.json else "Structure.txt"
    output_path = (
        Path(args.output).resolve() if args.output else (root / default_filename).resolve()
    )

    # Ensure the output parent directory exists before running the pipeline.
    # The output file itself is created only at the final write step.
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.exit(f"Error: cannot create output directory {output_path.parent}: {e}")

    extra_exclusions: frozenset[str] = (
        frozenset(args.exclude) if args.exclude else frozenset()
    )

    # If --env is provided, skip detection entirely and use the requested profile.
    # A sentinel DetectionResult is constructed to satisfy Config's type contract;
    # its values are never rendered because env_overridden=True causes the header
    # to display "(manual override)" instead of the confidence label.
    if args.env is not None:
        if args.debug_detect:
            print("Detection skipped: --env override was provided.", file=sys.stderr)
        profile = _profile_for_name(args.env)
        detection_result = DetectionResult(
            environment=Environment.UNKNOWN,
            confidence=Confidence.UNKNOWN,
            java_score=0,
            web_score=0,
            clues_matched=(),
        )
        env_overridden = True
    else:
        detection_result = detect(root)
        if args.debug_detect:
            _print_debug_detect(detection_result)
        profile = _profile_for_detection(detection_result)
        env_overridden = False

    # --no-node-modules: promote node_modules from collapsed to excluded.
    # Both sets must be updated atomically via dataclasses.replace because
    # EnvironmentProfile enforces disjointness between them in __post_init__.
    if args.no_node_modules:
        profile = dataclasses.replace(
            profile,
            collapsed_dirs=profile.collapsed_dirs - {"node_modules"},
            excluded_dirs=profile.excluded_dirs | {"node_modules"},
        )

    config = Config(
        root=root,
        profile=profile,
        output_path=output_path,
        use_ascii=args.ascii,
        extra_exclusions=extra_exclusions,
        env_overridden=env_overridden,
        detection_result=detection_result,
    )

    nodes = scan(root, profile, output_path, extra_exclusions)
    nodes = annotate(nodes, profile)
    text = render_json(nodes, config) if args.json else render_text(nodes, config)

    try:
        write_output(text, config)
    except OSError as e:
        sys.exit(f"Error: failed to write output file {output_path}: {e}")

    print(f"Written: {output_path}", file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tree",
        description="Generate an annotated project file tree.",
    )
    parser.add_argument(
        "--root",
        default=".",
        metavar="PATH",
        help="Root directory to scan (default: current directory).",
    )
    parser.add_argument(
        "--env",
        choices=["java", "web"],
        default=None,
        metavar="{java,web}",
        help="Override environment detection.",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help=(
            "Output file path. Defaults to <root>/Structure.txt, "
            "or <root>/Structure.json when --json is active."
        ),
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="Use ASCII characters instead of Unicode box-drawing.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        metavar="DIR",
        help="Additional directory name to exclude. Repeatable.",
    )
    parser.add_argument(
        "--debug-detect",
        action="store_true",
        default=False,
        help="Print environment detection detail to stderr. No effect on output file.",
    )
    parser.add_argument(
        "--no-node-modules",
        action="store_true",
        default=False,
        help="Exclude node_modules entirely instead of collapsing it. Web profile only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Write JSON output instead of plain text. Default filename becomes Structure.json.",
    )
    return parser.parse_args()


def _print_debug_detect(result: DetectionResult) -> None:
    """
    Print detection detail to stderr.

    Covers: per-environment scores, confidence level, and each clue that fired.
    Called only when --debug-detect is active and detection actually ran.
    Sentinel results (produced when --env is used) are never passed here.
    """
    print("Detection detail:", file=sys.stderr)
    print(f"  java score : {result.java_score}", file=sys.stderr)
    print(f"  web score  : {result.web_score}", file=sys.stderr)
    print(f"  confidence : {result.confidence.name.lower()}", file=sys.stderr)
    if result.clues_matched:
        print("  clues matched:", file=sys.stderr)
        for clue in result.clues_matched:
            print(f"    - {clue}", file=sys.stderr)
    else:
        print("  clues matched: none", file=sys.stderr)


def _profile_for_name(name: str) -> EnvironmentProfile:
    """Return the profile constant for an explicit --env value."""
    return {"java": JAVA_PROFILE, "web": WEB_PROFILE}[name]


def _profile_for_detection(result: DetectionResult) -> EnvironmentProfile:
    """
    Select a profile based on detection result.

    Emits a warning to stderr when confidence is not CONFIDENT so the user
    knows they may want to pass --env. Never exits - the run continues with
    the best available profile.
    """
    if result.environment == Environment.JAVA and result.confidence == Confidence.CONFIDENT:
        return JAVA_PROFILE

    if result.environment == Environment.WEB and result.confidence == Confidence.CONFIDENT:
        return WEB_PROFILE

    # LOW confidence or UNKNOWN environment: warn and fall back to UNKNOWN_PROFILE.
    if result.confidence == Confidence.LOW:
        print(
            f"Warning: environment detection is ambiguous "
            f"(java={result.java_score}, web={result.web_score}). "
            f"Using UNKNOWN profile. Pass --env to override.",
            file=sys.stderr,
        )
    else:
        print(
            "Warning: environment could not be detected. "
            "Using UNKNOWN profile. Pass --env to override.",
            file=sys.stderr,
        )

    return UNKNOWN_PROFILE


if __name__ == "__main__":
    main()
