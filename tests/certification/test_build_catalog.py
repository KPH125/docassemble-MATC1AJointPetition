from pathlib import Path
import json
import unittest

from build_catalog import build_catalog


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((HERE / "baseline.json").read_text())
        cls.catalog = build_catalog(WORKSPACE, cls.baseline)

    def test_catalog_resolves_every_local_combined_include(self):
        unresolved_local = [
            include
            for include in self.catalog["unresolved_external_includes"]
            if include.split(":", 1)[0] in self.baseline["packages"]
        ]
        self.assertEqual(unresolved_local, [])

    def test_every_unresolved_include_is_declared_external(self):
        unresolved_packages = {
            include.split(":", 1)[0]
            for include in self.catalog["unresolved_external_includes"]
        }
        self.assertTrue(
            unresolved_packages.issubset(set(self.baseline["external_packages"])),
            f"undeclared external packages: {unresolved_packages - set(self.baseline['external_packages'])}",
        )

    def test_catalog_contains_known_combined_screens_and_orders(self):
        screen_ids = {screen["id"] for screen in self.catalog["screens"]}
        for screen_id in (
            "existing 1B action screener",
            "choose forms to include",
            "Agreement on major issues",
            "r408 demographics",
            "child support worksheet result",
            "download divorce joint petition",
        ):
            self.assertIn(screen_id, screen_ids)

    def test_catalog_finds_known_top_level_branch_conditions(self):
        expressions = {branch["expression"] for branch in self.catalog["branches"]}
        self.assertIn("has_existing_1b_action", expressions)
        self.assertIn("ask_if_qualifies_for_fee_waiver", expressions)
        self.assertIn('separation_agreement_format == "interview"', expressions)

    def test_catalog_captures_non_fields_question_variables(self):
        sign_variants = [
            screen for screen in self.catalog["screens"] if screen["id"] == "sign party A"
        ]
        self.assertEqual(len(sign_variants), 2)
        self.assertEqual(
            {tuple(screen["variables"]) for screen in sign_variants},
            {("users[0].signature",)},
        )


if __name__ == "__main__":
    unittest.main()
