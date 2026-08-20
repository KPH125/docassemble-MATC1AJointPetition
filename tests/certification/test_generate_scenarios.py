import json
import tempfile
import unittest
from pathlib import Path

import yaml

from generate_scenarios import generate


HERE = Path(__file__).resolve().parent


class ScenarioGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = yaml.safe_load((HERE / "coverage_model.yml").read_text())

    def test_every_declared_path_is_materialized(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = generate(self.model, Path(directory))
            self.assertEqual(len(paths), len(self.model["modeled_paths"]))
            self.assertEqual(len(paths), len({path.name for path in paths}))
            for path in paths:
                scenario = json.loads(path.read_text())
                self.assertTrue(scenario["expected_terminal_ids"])
                self.assertTrue(scenario["probe_events"])

    def test_every_dimension_value_appears_in_defaults_or_an_override(self):
        observed = {key: {self._freeze(value)} for key, value in self.model["default_variables"].items()}
        for path in self.model["modeled_paths"]:
            for key, value in path.get("overrides", {}).items():
                observed.setdefault(key, set()).add(self._freeze(value))

        # Derived checkbox booleans are covered by the explicit checkbox paths.
        derived = {"divorce_affirm", "joint_petition_affirm"}
        for variable, values in self.model["dimensions"].items():
            if variable in derived:
                continue
            if variable == "notarize_affirm":
                continue
            expected = {self._freeze(value) for value in values}
            self.assertTrue(
                expected.issubset(observed.get(variable, set())),
                f"missing modeled values for {variable}: {expected - observed.get(variable, set())}",
            )

    @staticmethod
    def _freeze(value):
        if isinstance(value, dict):
            return tuple(sorted((key, ScenarioGenerationTests._freeze(item)) for key, item in value.items()))
        if isinstance(value, list):
            return tuple(ScenarioGenerationTests._freeze(item) for item in value)
        return value


if __name__ == "__main__":
    unittest.main()
