#!/usr/bin/env python3
"""Audit runtime evidence against the declared static and path models."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def normalized_variable(value: Any) -> str:
    return re.sub(r"\[\d+\]", "[i]", str(value or ""))


def static_variant_signature(screen: dict[str, Any]) -> tuple[Any, ...]:
    return (
        screen.get("event"),
        normalized_variable(screen.get("continue_button_field")),
        tuple(sorted(normalized_variable(value) for value in screen.get("sets") or [])),
        tuple(sorted(normalized_variable(value) for value in screen.get("variables") or [])),
    )


def audit(
    catalog: dict[str, Any],
    ledger: dict[str, Any],
    classifications: dict[str, Any],
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    declared = {screen["id"] for screen in catalog["screens"]}
    observed = {
        screen_id
        for result in ledger.get("results", [])
        for screen_id in result.get("seen_screen_ids", [])
    }
    static_variants: dict[str, set[tuple[Any, ...]]] = {}
    for screen in catalog["screens"]:
        static_variants.setdefault(screen["id"], set()).add(static_variant_signature(screen))
    observed_variants: dict[str, set[str]] = {}
    for result in ledger.get("results", []):
        for step in result.get("steps", []):
            if step.get("id") and step.get("variant_fingerprint"):
                observed_variants.setdefault(step["id"], set()).add(step["variant_fingerprint"])
    has_variant_evidence = bool(observed_variants)
    missing_screen_variants = (
        {
            screen_id: {
                "expected": len(signatures),
                "observed": len(observed_variants.get(screen_id, set())),
            }
            for screen_id, signatures in static_variants.items()
            if len(observed_variants.get(screen_id, set())) < len(signatures)
            and screen_id in observed
        }
        if has_variant_evidence
        else {}
    )
    exclusions = classifications.get("proven_unreachable", {})
    excluded = set(exclusions)
    missing = declared - observed - excluded
    stale_exclusions = excluded - declared
    failed_paths = [
        {
            "name": result.get("name"),
            "failure": result.get("failure"),
            "last_screen": (result.get("steps") or [{}])[-1].get("id"),
        }
        for result in ledger.get("results", [])
        if result.get("status") != "pass"
    ]
    unsupported_exclusions = [
        screen_id for screen_id, reason in exclusions.items() if not str(reason).strip()
    ]
    expected_paths = {path["name"] for path in (model or {}).get("modeled_paths", [])}
    observed_paths = {result.get("name") for result in ledger.get("results", [])}
    missing_paths = expected_paths - observed_paths
    unexpected_paths = observed_paths - expected_paths if expected_paths else set()
    passed = (
        not missing
        and not stale_exclusions
        and not failed_paths
        and not unsupported_exclusions
        and not missing_paths
        and not unexpected_paths
        and not missing_screen_variants
    )
    return {
        "passed": passed,
        "declared_local_screen_ids": len(declared),
        "observed_screen_ids": len(observed),
        "observed_local_screen_ids": len(declared & observed),
        "observed_external_screen_ids": sorted(observed - declared),
        "proven_unreachable_screen_ids": len(excluded & declared),
        "missing_local_screen_ids": sorted(missing),
        "stale_exclusions": sorted(stale_exclusions),
        "unsupported_exclusions": sorted(unsupported_exclusions),
        "missing_modeled_paths": sorted(missing_paths),
        "unexpected_runtime_paths": sorted(unexpected_paths),
        "failed_paths": failed_paths,
        "missing_screen_variants": missing_screen_variants,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=HERE / "static_catalog.json")
    parser.add_argument("--ledger", type=Path, default=HERE / "runtime_ledger.json")
    parser.add_argument("--classifications", type=Path, default=HERE / "screen_classification.yml")
    parser.add_argument("--model", type=Path, default=HERE / "coverage_model.yml")
    parser.add_argument("--output", type=Path, default=HERE / "coverage_audit.json")
    args = parser.parse_args()
    classifications = yaml.safe_load(args.classifications.read_text()) if args.classifications.exists() else {}
    model = yaml.safe_load(args.model.read_text()) if args.model.exists() else {}
    report = audit(load_json(args.catalog), load_json(args.ledger), classifications or {}, model or {})
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
