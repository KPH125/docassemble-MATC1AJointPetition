import unittest

from audit_coverage import audit


class CoverageAuditTests(unittest.TestCase):
    def test_unobserved_framework_utility_is_not_a_combined_feature_obligation(self):
        catalog = {
            "screens": [
                {"id": "feature", "coverage_scope": "combined_feature"},
                {"id": "saved sessions", "coverage_scope": "framework_support"},
            ]
        }
        ledger = {
            "results": [{
                "name": "path",
                "status": "pass",
                "seen_screen_ids": ["feature"],
            }]
        }
        report = audit(catalog, ledger, {"proven_unreachable": {}})
        self.assertTrue(report["passed"])
        self.assertEqual(report["unobserved_framework_catalog_screens"], 1)

    def test_missing_cardinality_class_fails(self):
        catalog = {"screens": [{"id": "one"}]}
        ledger = {
            "results": [{
                "name": "path",
                "status": "pass",
                "seen_screen_ids": ["one"],
                "cardinality_evidence": {
                    "items": {"expected": 1, "observed": 1},
                },
            }]
        }
        model = {
            "modeled_paths": [{"name": "path"}],
            "cardinality_classes": {"items": [0, 1, 2]},
        }
        report = audit(catalog, ledger, {"proven_unreachable": {}}, model)
        self.assertFalse(report["passed"])
        self.assertEqual(report["missing_cardinality_classes"], {"items": [0, 2]})

    def test_missing_declared_screen_fails(self):
        catalog = {"screens": [{"id": "one"}, {"id": "two"}]}
        ledger = {"results": [{"name": "path", "status": "pass", "seen_screen_ids": ["one"]}]}
        report = audit(catalog, ledger, {"proven_unreachable": {}})
        self.assertFalse(report["passed"])
        self.assertEqual(report["missing_local_screen_ids"], ["two"])

    def test_reasoned_unreachable_classification_satisfies_denominator(self):
        catalog = {"screens": [{"id": "one"}, {"id": "standalone only"}]}
        ledger = {"results": [{"name": "path", "status": "pass", "seen_screen_ids": ["one"]}]}
        report = audit(
            catalog,
            ledger,
            {"proven_unreachable": {"id:standalone only": "Not called by the combined parent order."}},
        )
        self.assertTrue(report["passed"])

    def test_runtime_observation_contradicts_unreachable_classification(self):
        catalog = {"screens": [{"id": "one"}]}
        ledger = {
            "results": [{
                "name": "path",
                "status": "pass",
                "seen_screen_ids": ["one"],
            }]
        }
        report = audit(
            catalog,
            ledger,
            {"proven_unreachable": {"id:one": "Incorrectly classified."}},
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["observed_exclusions"], ["id:one"])

    def test_failed_runtime_path_fails_even_with_full_screen_coverage(self):
        catalog = {"screens": [{"id": "one"}]}
        ledger = {
            "results": [
                {
                    "name": "path",
                    "status": "fail",
                    "failure": "request_timeout",
                    "seen_screen_ids": ["one"],
                    "steps": [{"id": "one"}],
                }
            ]
        }
        report = audit(catalog, ledger, {"proven_unreachable": {}})
        self.assertFalse(report["passed"])
        self.assertEqual(report["failed_paths"][0]["failure"], "request_timeout")

    def test_missing_modeled_path_fails(self):
        catalog = {"screens": [{"id": "one"}]}
        ledger = {"results": [{"name": "ran", "status": "pass", "seen_screen_ids": ["one"]}]}
        model = {"modeled_paths": [{"name": "ran"}, {"name": "not run"}]}
        report = audit(catalog, ledger, {"proven_unreachable": {}}, model)
        self.assertFalse(report["passed"])
        self.assertEqual(report["missing_modeled_paths"], ["not run"])

    def test_duplicate_id_requires_each_exact_source_block(self):
        catalog = {
            "screens": [
                {
                    "id": "shared",
                    "source_file": "docassemble.example:data/questions/one.yml",
                    "source_fingerprint": "first",
                },
                {
                    "id": "shared",
                    "source_file": "docassemble.example:data/questions/two.yml",
                    "source_fingerprint": "second",
                },
            ]
        }
        ledger = {
            "results": [{
                "name": "path",
                "status": "pass",
                "seen_screen_ids": ["shared"],
                "steps": [{
                    "id": "shared",
                    "source_file": "docassemble.example:data/questions/one.yml",
                    "source_fingerprint": "first",
                }],
            }]
        }
        report = audit(catalog, ledger, {"proven_unreachable": {}})
        self.assertFalse(report["passed"])
        self.assertEqual(
            report["missing_local_screens"],
            [{
                "coordinate": "docassemble.example:data/questions/two.yml#second",
                "id": "shared",
                "source_file": "docassemble.example:data/questions/two.yml",
                "document_index": None,
            }],
        )

    def test_unique_fingerprint_resolves_abbreviated_runtime_source_file(self):
        catalog = {
            "screens": [{
                "id": "petition",
                "source_file": "docassemble.example:data/questions/petition.yml",
                "source_fingerprint": "exact-block",
            }]
        }
        ledger = {
            "results": [{
                "name": "path",
                "status": "pass",
                "steps": [{
                    "id": "petition",
                    "source_file": "petition.yml",
                    "source_fingerprint": "exact-block",
                }],
            }]
        }
        report = audit(catalog, ledger, {"proven_unreachable": {}})
        self.assertTrue(report["passed"])
        self.assertEqual(report["observed_local_screens"], 1)


if __name__ == "__main__":
    unittest.main()
