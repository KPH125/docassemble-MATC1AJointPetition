#!/usr/bin/env python3
"""Measure deterministic clinic dashboard projection and filtering costs."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docassemble.MATC1ADivorceJointPetition.clinic_workspace import (  # noqa: E402
    assign_team_member,
    filter_visible_summaries,
    new_matter,
    safe_matter_summary,
)


FIXED_NOW = datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)


def build_fixture(size: int) -> List[Dict]:
    summaries: List[Dict] = []
    for index in range(size):
        owner_id = 100 + (index % 50)
        matter = new_matter(
            owner_id,
            f"MAT-{index:06d}",
            matter_id=f"matter-{index}",
            now=FIXED_NOW,
        )
        assign_team_member(
            matter,
            1000 + (index % 5),
            "supervisor",
            owner_id,
            now=FIXED_NOW,
        )
        if index % 7 == 0:
            matter["next_action"] = "supervisor_review"
        if index % 11 == 0:
            matter["overall_status"] = "closed"
        summaries.append(safe_matter_summary(matter))
    return summaries


def percentile(values: List[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile_value))
    return ordered[index]


def measure(size: int, repeats: int) -> Dict:
    fixture_started = perf_counter()
    summaries = build_fixture(size)
    fixture_seconds = perf_counter() - fixture_started

    filter_seconds: List[float] = []
    review_seconds: List[float] = []
    for _ in range(repeats):
        started = perf_counter()
        filter_visible_summaries(
            summaries, 101, ["clinic_student"], limit=25
        )
        filter_seconds.append(perf_counter() - started)

        started = perf_counter()
        filter_visible_summaries(
            summaries,
            1001,
            ["clinic_supervisor"],
            needs_review=True,
            limit=25,
        )
        review_seconds.append(perf_counter() - started)

    return {
        "matter_count": size,
        "fixture_seconds": fixture_seconds,
        "assigned_filter_p50_seconds": statistics.median(filter_seconds),
        "assigned_filter_p95_seconds": percentile(filter_seconds, 0.95),
        "review_filter_p50_seconds": statistics.median(review_seconds),
        "review_filter_p95_seconds": percentile(review_seconds, 0.95),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 500, 1000])
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repeats": args.repeats,
        "results": [measure(size, args.repeats) for size in args.sizes],
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)

    largest = report["results"][-1]
    if largest["assigned_filter_p95_seconds"] >= 2.0:
        return 1
    if largest["review_filter_p95_seconds"] >= 1.5:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
