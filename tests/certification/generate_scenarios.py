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
