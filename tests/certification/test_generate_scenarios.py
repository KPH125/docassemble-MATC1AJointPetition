import json
import tempfile
import unittest
from pathlib import Path

from yaml.constructor import ConstructorError

from generate_scenarios import (
    expected_bundle_documents,
    expected_cardinalities,
    expected_terminal_evidence,
    generate,
)
from model_loader import load_model


HERE = Path(__file__).resolve().parent


class ScenarioGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_model(HERE / "coverage_model.yml")

    def test_every_declared_path_is_materialized(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = generate(self.model, Path(directory))
            self.assertEqual(len(paths), len(self.model["modeled_paths"]))
            self.assertEqual(len(paths), len({path.name for path in paths}))
            for path in paths:
                scenario = json.loads(path.read_text())
                self.assertTrue(scenario["expected_terminal_ids"])
                self.assertTrue(scenario["expected_terminal_evidence"])
                self.assertTrue(scenario["expected_bundle_documents"])
                self.assertTrue(scenario["probe_events"])

    def test_financial_paths_explicitly_choose_schedule_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = generate(self.model, Path(directory))
            for path in paths:
                scenario = json.loads(path.read_text())
                if scenario["family"] != "financial":
                    continue
                variables = scenario["variables"]
                scope = variables["financial_statement_scope"]
                selected_indexes = []
                if scope in ("spouse_1_only", "both"):
                    selected_indexes.append(0)
                if scope in ("spouse_2_only", "both"):
                    selected_indexes.append(1)
                for index in selected_indexes:
                    self.assertIn(
                        f"users[{index}].has_self_employment_income", variables
                    )
                    self.assertIn(f"users[{index}].has_rental_income", variables)

    def test_model_loader_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "ambiguous.yml"
            model_path.write_text("dimensions:\n  branch: true\n  branch: false\n")
            with self.assertRaises(ConstructorError):
                load_model(model_path)

    def test_bundle_evidence_is_derived_from_path_inputs(self):
        evidence = expected_terminal_evidence({
            "children_of_marriage": True,
            "has_existing_1b_action": False,
            "financial_statement_scope": "spouse_1_only",
            "separation_agreement_format": "interview",
            "csg_worksheet_path": "interview",
            "child_support_deviation": True,
            "marriage_certificate_upload": "uploaded.pdf",
        })
        self.assertTrue(evidence["include_r408"])
        self.assertTrue(evidence["include_care_or_custody_affidavit"])
        self.assertTrue(evidence["include_child_support_guidelines_worksheet"])
        self.assertTrue(evidence["include_financial_statement"])
        self.assertTrue(evidence["include_financial_statement_spouse_1"])
        self.assertFalse(evidence["include_financial_statement_spouse_2"])
        self.assertTrue(evidence["include_separation_agreement"])
        self.assertTrue(evidence["include_findings_and_determinations"])
        self.assertFalse(evidence["needs_late_marriage_certificate_motion"])

    def test_cardinality_evidence_is_derived_from_path_inputs(self):
        evidence = expected_cardinalities(
            self.model,
            {"children_of_marriage_number": 5},
            {"other_care_custody_proceedings": 2},
        )
        self.assertEqual(evidence["users"]["expected"], 2)
        self.assertEqual(evidence["children"]["expected"], 5)
        self.assertEqual(evidence["other_care_custody_proceedings"]["expected"], 2)

    def test_exact_bundle_membership_is_derived_from_path_inputs(self):
        evidence = expected_bundle_documents({
            "children_of_marriage": True,
            "has_existing_1b_action": False,
            "financial_statement_scope": "spouse_1_only",
            "users[0].gross_annual_income": 75000,
            "users[0].has_self_employment_income": True,
            "separation_agreement_format": "interview",
            "csg_worksheet_path": "interview",
            "child_support_deviation": True,
            "marriage_certificate_upload": "uploaded.pdf",
            "ask_if_qualifies_for_fee_waiver": False,
        })
        self.assertTrue(evidence["users[0].financial_statement_long_attachment"])
        self.assertFalse(evidence["users[0].financial_statement_short_attachment"])
        self.assertTrue(evidence["users[0].financial_statement_schedule_a_attachment"])
        self.assertFalse(evidence["users[1].financial_statement_long_attachment"])
        self.assertTrue(evidence["a_divorce_agreement_attachment"])
        self.assertTrue(evidence["cjd_305_attachment"])
        self.assertFalse(evidence["jointmotiontofilemarriagecertificatelate_attachment"])

    def test_every_dimension_value_appears_in_defaults_or_an_override(self):
        observed = {}
        self._record_values(observed, self.model["default_variables"])
        for path in self.model["modeled_paths"]:
            self._record_values(observed, path.get("overrides", {}))

        for variable, values in self.model["dimensions"].items():
            expected = {self._freeze(value) for value in values}
            self.assertTrue(
                expected.issubset(observed.get(variable, set())),
                f"missing modeled values for {variable}: {expected - observed.get(variable, set())}",
            )

    @classmethod
    def _record_values(cls, observed, values, prefix=""):
        for key, value in values.items():
            variable = f"{prefix}.{key}" if prefix else key
            observed.setdefault(variable, set()).add(cls._freeze(value))
            if isinstance(value, dict) and "$file" not in value and "$sequence" not in value:
                cls._record_values(observed, value, variable)

    @staticmethod
    def _freeze(value):
        if isinstance(value, dict):
            return tuple(sorted((key, ScenarioGenerationTests._freeze(item)) for key, item in value.items()))
        if isinstance(value, list):
            return tuple(ScenarioGenerationTests._freeze(item) for item in value)
        return value


if __name__ == "__main__":
    unittest.main()
