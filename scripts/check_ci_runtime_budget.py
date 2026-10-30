#!/usr/bin/env python3
"""CI runtime budget verification script.

Evaluates job elapsed runtime against a maximum duration threshold and outputs
GitHub Actions annotations and markdown step summaries.

Standard library only, compatible with Python 3.11+.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify CI job elapsed runtime against configured maximum budget threshold."
    )
    parser.add_argument(
        "--start-epoch",
        type=str,
        default="",
        help="CI job start timestamp in epoch seconds.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=300.0,
        help="Maximum allowable job runtime in seconds (default: 300.0).",
    )
    parser.add_argument(
        "--step-summary",
        type=str,
        default="",
        help="Optional path to GITHUB_STEP_SUMMARY file to append summary markdown table.",
    )
    return parser.parse_args(argv)


def escape_annotation(message: str) -> str:
    """Format workflow command text escaping characters treated specially by GitHub Actions."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def write_step_summary(summary_path_str: str, elapsed: float, max_seconds: float, passed: bool) -> None:
    """Append CI runtime budget check results to the GitHub step summary file."""
    if not summary_path_str.strip():
        return

    summary_path = Path(summary_path_str)
    try:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        pct_str = f"{(elapsed / max_seconds * 100):.1f}" if max_seconds > 0 else "N/A"
        status_str = "PASS" if passed else "FAIL"

        markdown = (
            "### CI Runtime Budget Check\n\n"
            "| Metric | Value |\n"
            "| :--- | :--- |\n"
            f"| Elapsed Duration | {elapsed:.1f} s |\n"
            f"| Maximum Budget | {max_seconds:.1f} s |\n"
            f"| Budget Utilization | {pct_str}% |\n"
            f"| Status | {status_str} |\n\n"
        )

        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(markdown)
    except OSError as err:
        print(f"::warning::Unable to write CI runtime budget step summary: {err}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    raw_start = args.start_epoch.strip()
    if not raw_start:
        print("::notice::CI timing gate: start epoch not set or empty; skipping runtime budget check.")
        return 0

    try:
        start_epoch = float(raw_start)
    except ValueError:
        print(
            f"::warning::CI timing gate: invalid start epoch {raw_start!r}; skipping runtime budget check."
        )
        return 0

    if start_epoch <= 0:
        print(
            f"::warning::CI timing gate: non-positive start epoch {start_epoch}; skipping runtime budget check."
        )
        return 0

    current_epoch = time.time()
    elapsed = max(0.0, current_epoch - start_epoch)
    max_seconds = max(0.0, args.max_seconds)
    passed = elapsed <= max_seconds

    pct_str = f"{(elapsed / max_seconds * 100):.1f}%" if max_seconds > 0 else "N/A"
    print(
        f"CI runtime budget check: elapsed {elapsed:.1f}s, maximum budget {max_seconds:.1f}s ({pct_str})"
    )

    if args.step_summary:
        write_step_summary(args.step_summary, elapsed, max_seconds, passed)

    if not passed:
        err_msg = f"Job runtime ({elapsed:.1f}s) exceeded budget ({max_seconds:.1f}s)"
        print(f"::error::{escape_annotation(err_msg)}")
        return 1

    notice_msg = f"Job runtime ({elapsed:.1f}s) is within budget ({max_seconds:.1f}s)"
    print(f"::notice::{escape_annotation(notice_msg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
