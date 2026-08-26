#!/usr/bin/env python3
"""Materialize the finite modeled paths as deterministic JSON scenarios."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from model_loader import load_model


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


def expected_bundle_documents(variables: dict) -> dict[str, bool]:
    """Return the exact generated-document membership for a modeled route."""
    terminal = expected_terminal_evidence(variables)
    scope = variables.get("financial_statement_scope", "neither")
    selected_users = {
        0: scope in ("both", "spouse_1_only"),
        1: scope in ("both", "spouse_2_only"),
    }
    expected = {
        "motion_to_amend_attachment": bool(variables.get("has_existing_1b_action")),
        "divorcejointpetition_Post_interview_instructions": True,
        "divorcejointpetition_attachment": True,
        "affidavit_attachment": True,
        "r408_attachment": terminal["include_r408"],
        "jointmotiontofilemarriagecertificatelate_attachment": terminal[
            "needs_late_marriage_certificate_motion"
        ],
        # This modeled fee-waiver route uses the harness's low-income answers
        # and must finish with an indigency form in the packet.
        "affidavitofindigency_attachment": bool(
            variables.get("ask_if_qualifies_for_fee_waiver")
            and variables.get("fee_waiver_qualifies", True)
        ),
        "child_care_or_custody_disclosure_affidavit_next_steps": terminal[
            "include_care_or_custody_affidavit"
        ],
        "affidavit_of_care_or_custody_attachment": terminal[
            "include_care_or_custody_affidavit"
        ],
        "ma_child_support_guidelines_worksheet_attachment": terminal[
            "include_child_support_guidelines_worksheet"
        ],
        "cjd_305_attachment": terminal["include_findings_and_determinations"],
        "a_divorce_agreement_Post_interview_instructions": terminal[
            "include_separation_agreement"
        ],
        "a_divorce_agreement_attachment": terminal["include_separation_agreement"],
    }
    for index, selected in selected_users.items():
        income = variables.get(f"users[{index}].gross_annual_income", 0)
        form_type = "long" if selected and float(income) >= 75000 else "short"
        expected[f"users[{index}].financial_statement_short_attachment"] = (
            selected and form_type == "short"
        )
        expected[f"users[{index}].financial_statement_long_attachment"] = (
            selected and form_type == "long"
        )
        expected[f"users[{index}].financial_statement_schedule_a_attachment"] = (
            selected and bool(variables.get(f"users[{index}].has_self_employment_income"))
        )
        expected[f"users[{index}].financial_statement_schedule_b_attachment"] = (
            selected and bool(variables.get(f"users[{index}].has_rental_income"))
        )
    return expected


def expected_cardinalities(
    model: dict,
    variables: dict,
    path_cardinalities: dict | None = None,
) -> dict:
    result = {}
    path_cardinalities = path_cardinalities or {}
    for name, probe in model.get("cardinality_probes", {}).items():
        if probe.get("when_variable") and not variables.get(probe["when_variable"]):
            continue
        if probe.get("when_values") and variables.get(probe["when_variable"]) not in probe["when_values"]:
            continue
        if name in path_cardinalities:
            count = path_cardinalities[name]
        elif "parent_cardinality" in probe:
            parent_count = result[probe["parent_cardinality"]]["expected"]
            if isinstance(parent_count, list):
                raise ValueError(f"parent cardinality for {name} must be scalar")
            count = [probe["default_count"] for _ in range(parent_count)]
        elif "per_parent_count_variable" in probe:
            count = [
                probe["default_count"]
                for _ in range(int(variables[probe["per_parent_count_variable"]]))
            ]
        elif "fixed_count" in probe:
            count = probe["fixed_count"]
        elif "count_variable" in probe:
            count = variables[probe["count_variable"]]
        else:
            count = probe["default_count"]
        result[name] = {
            "variable": probe["variable"],
            "expected": [int(item) for item in count] if isinstance(count, list) else int(count),
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
        terminal_assertions = path.get("terminal_assertions", True)
        scenario = {
            "name": path["name"],
            "family": path["family"],
            "interview": model["entrypoint"],
            "variables": variables,
            "expected_terminal_ids": path.get(
                "expected_terminal_ids", model.get("default_terminal_ids", [])
            ),
            "required_screen_ids": path.get("required_screen_ids", []),
            "forbidden_screen_ids": path.get("forbidden_screen_ids", []),
            "terminal_assertions": terminal_assertions,
            "expected_terminal_evidence": path.get(
                "expected_terminal_evidence",
                expected_terminal_evidence(variables) if terminal_assertions else {},
            ),
            "expected_bundle_documents": path.get(
                "expected_bundle_documents",
                expected_bundle_documents(variables) if terminal_assertions else {},
            ),
            "expected_cardinalities": path.get(
                "expected_cardinalities",
                expected_cardinalities(model, variables, path.get("cardinalities"))
                if terminal_assertions
                else {},
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
    paths = generate(load_model(args.model), args.output)
    print(f"generated {len(paths)} modeled paths in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
