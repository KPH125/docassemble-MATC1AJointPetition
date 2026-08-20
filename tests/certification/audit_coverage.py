#!/usr/bin/env python3
"""Audit runtime evidence against the declared static and path models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from model_loader import load_model


HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def screen_coordinate(screen: dict[str, Any]) -> str:
    """Identify one exact YAML screen block, even when IDs are reused."""
    if screen.get("source_file") and screen.get("source_fingerprint"):
        return f"{screen['source_file']}#{screen['source_fingerprint']}"
    return f"id:{screen.get('id', '<unnamed>')}"


def runtime_screen_records(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for result in ledger.get("results", []):
        result_records = list(result.get("steps", [])) + list(result.get("event_probes", []))
        if result_records:
            records.extend(result_records)
        else:
            # Compatibility for small hand-built ledgers and historical runs;
            # production ledgers always carry exact per-step coordinates.
            records.extend({"id": screen_id} for screen_id in result.get("seen_screen_ids", []))
    return records


def audit(
    catalog: dict[str, Any],
    ledger: dict[str, Any],
    classifications: dict[str, Any],
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_records = runtime_screen_records(ledger)
    observed_coordinates = {screen_coordinate(record) for record in runtime_records}
    observed_ids = {
        str(record["id"])
        for record in runtime_records
        if record.get("id")
    }
    feature_screens = [
        screen
        for screen in catalog["screens"]
        if screen.get("coverage_scope", "combined_feature") == "combined_feature"
    ]
    framework_screens = [
        screen
        for screen in catalog["screens"]
        if screen.get("coverage_scope") == "framework_support"
    ]
    feature_declared = {screen_coordinate(screen) for screen in feature_screens}
    framework_catalog = {screen_coordinate(screen) for screen in framework_screens}
    # Feature-package screens are exhaustive obligations. Framework packages
    # also contain generic saved-session, authoring, and standalone utility
    # screens that this interview never calls; any framework screen actually
    # observed at runtime joins the obligation set automatically.
    declared = feature_declared | (framework_catalog & observed_coordinates)
    exclusions = classifications.get("proven_unreachable", {})
    excluded = set(exclusions)
    missing = declared - observed_coordinates - excluded
    stale_exclusions = excluded - declared
    catalog_by_coordinate = {
        screen_coordinate(screen): screen
        for screen in catalog["screens"]
    }
    missing_screens = [
        {
            "coordinate": coordinate,
            "id": catalog_by_coordinate[coordinate]["id"],
            "source_file": catalog_by_coordinate[coordinate].get("source_file"),
            "document_index": catalog_by_coordinate[coordinate].get("document_index"),
        }
        for coordinate in sorted(missing)
    ]
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
    expected_cardinality_classes = {
        name: set(values)
        for name, values in (model or {}).get("cardinality_classes", {}).items()
    }
    observed_cardinality_classes: dict[str, set[int]] = {}
    for result in ledger.get("results", []):
        if result.get("status") != "pass":
            continue
        for name, evidence in result.get("cardinality_evidence", {}).items():
            observed_value = evidence.get("observed")
            values = observed_value if isinstance(observed_value, list) else [observed_value]
            for value in values:
                if isinstance(value, int):
                    observed_cardinality_classes.setdefault(name, set()).add(value)
    missing_cardinality_classes = {
        name: sorted(values - observed_cardinality_classes.get(name, set()))
        for name, values in expected_cardinality_classes.items()
        if values - observed_cardinality_classes.get(name, set())
    }
    passed = (
        not missing
        and not stale_exclusions
        and not failed_paths
        and not unsupported_exclusions
        and not missing_paths
        and not unexpected_paths
        and not missing_cardinality_classes
    )
    return {
        "passed": passed,
        "declared_local_screens": len(declared),
        "declared_feature_screens": len(feature_declared),
        "declared_feature_screen_ids": len({screen["id"] for screen in feature_screens}),
        "observed_framework_screens": len(framework_catalog & observed_coordinates),
        "unobserved_framework_catalog_screens": len(framework_catalog - observed_coordinates),
        "observed_screen_coordinates": len(observed_coordinates),
        "observed_screen_ids": len(observed_ids),
        "observed_local_screens": len(declared & observed_coordinates),
        "observed_external_screen_coordinates": sorted(observed_coordinates - declared),
        "proven_unreachable_screen_ids": len(excluded & declared),
        "missing_local_screens": missing_screens,
        "missing_local_screen_ids": sorted({screen["id"] for screen in missing_screens}),
        "stale_exclusions": sorted(stale_exclusions),
        "unsupported_exclusions": sorted(unsupported_exclusions),
        "missing_modeled_paths": sorted(missing_paths),
        "unexpected_runtime_paths": sorted(unexpected_paths),
        "failed_paths": failed_paths,
        "missing_cardinality_classes": missing_cardinality_classes,
        "observed_cardinality_classes": {
            name: sorted(values)
            for name, values in observed_cardinality_classes.items()
        },
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
    model = load_model(args.model) if args.model.exists() else {}
    report = audit(load_json(args.catalog), load_json(args.ledger), classifications or {}, model or {})
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
