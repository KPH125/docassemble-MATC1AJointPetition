import unittest

from verify_runtime_manifest import freeze_digest, verify


BASELINE = {
    "runtime": {"image": "example/image@sha256:abc"},
    "external_packages": {"docassemble.Example": "1.2.3"},
}


class RuntimeManifestTests(unittest.TestCase):
    def test_freeze_digest_is_order_and_case_stable(self):
        self.assertEqual(
            freeze_digest("Zulu==2\nalpha==1\n"),
            freeze_digest("ALPHA==1\nzulu==2\n"),
        )

    def test_exact_manifest_passes(self):
        self.assertEqual(
            verify(
                BASELINE,
                ["example/image@sha256:abc"],
                "docassemble.Example==1.2.3\n",
            ),
            [],
        )

    def test_image_and_package_drift_fail(self):
        errors = verify(
            BASELINE,
            ["example/image@sha256:different"],
            "docassemble.Example==2.0.0\n",
        )
        self.assertEqual(len(errors), 2)
        self.assertIn("runtime image mismatch", errors[0])
        self.assertIn("package mismatch", errors[1])


if __name__ == "__main__":
    unittest.main()
