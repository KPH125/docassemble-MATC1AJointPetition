#!/usr/bin/env python3
"""Materialize the finite modeled paths as deterministic JSON scenarios."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def expected_terminal_evidence(variables: dict) -> dict[str, bool]:
    children = bool(variables.get("children_of_marriage"))
    existing_1b = bool(variables.get("has_existing_1b_action"))
    financial_scope = variables.get("financial_statement_scope", "neither")
    agreement_format = variables.get("separation_agreement_format", "wait")
    worksheet_path = variables.get("csg_worksheet_path", "wait")
    if not children or worksheet_path == "wait" or agreement_format == "wait":
        findings = False
    elif agreement_format == "interview":
        findings = bool(variables.get("child_support_deviation"))
    else:
        findings = bool(
            variables.get("uploaded_agreement_addresses_child_support")
            and variables.get("uploaded_agreement_child_support_deviation")
        )
    return {
        "include_r408": not existing_1b,
        "include_care_or_custody_affidavit": children,
        "include_child_support_guidelines_worksheet": children and worksheet_path == "interview",
        "include_financial_statement": financial_scope != "neither",
        "include_financial_statement_spouse_1": financial_scope in ("both", "spouse_1_only"),
        "include_financial_statement_spouse_2": financial_scope in ("both", "spouse_2_only"),
        "include_separation_agreement": agreement_format == "interview",
        "include_findings_and_determinations": findings,
        "needs_late_marriage_certificate_motion": not bool(
            variables.get("marriage_certificate_upload")
        ),
    }


def expected_cardinalities(model: dict, variables: dict) -> dict:
    result = {}
    for name, probe in model.get("cardinality_probes", {}).items():
        if "fixed_count" in probe:
            count = probe["fixed_count"]
        else:
            count = variables[probe["count_variable"]]
        result[name] = {
            "variable": probe["variable"],
            "expected": int(count),
        }
    return result


def generate(model: dict, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob("*.json"):
        old.unlink()
    written = []
    defaults = model.get("default_variables", {})
    for index, path in enumerate(model.get("modeled_paths", []), start=1):
        variables = dict(defaults)
        variables.update(path.get("overrides", {}))
        scenario = {
            "name": path["name"],
            "family": path["family"],
            "interview": model["entrypoint"],
            "variables": variables,
            "expected_terminal_ids": path.get(
                "expected_terminal_ids", model.get("default_terminal_ids", [])
            ),
            "expected_terminal_evidence": path.get(
                "expected_terminal_evidence", expected_terminal_evidence(variables)
            ),
            "expected_cardinalities": path.get(
                "expected_cardinalities", expected_cardinalities(model, variables)
            ),
            "probe_events": path.get(
                "probe_events", model.get("default_probe_events", [])
            ),
        }
        destination = output / f"{index:03d}_{slug(path['name'])}.json"
        destination.write_text(json.dumps(scenario, indent=2, sort_keys=True) + "\n")
        written.append(destination)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=HERE / "coverage_model.yml")
    parser.add_argument("--output", type=Path, default=HERE / "generated_scenarios")
    args = parser.parse_args()
    paths = generate(yaml.safe_load(args.model.read_text()), args.output)
    print(f"generated {len(paths)} modeled paths in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
