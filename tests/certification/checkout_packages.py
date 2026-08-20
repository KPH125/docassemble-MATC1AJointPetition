#!/usr/bin/env python3
"""Check out the exact local-package commits declared in baseline.json."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent


def run(*command: str, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--skip", action="append", default=[])
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text())
    args.workspace.mkdir(parents=True, exist_ok=True)

    for package, spec in baseline["packages"].items():
        if package in args.skip:
            continue
        destination = args.workspace / spec["directory"]
        if not destination.exists():
            run("git", "clone", f"https://github.com/{spec['repository']}.git", str(destination))
        run("git", "fetch", "--all", "--prune", cwd=destination)
        run("git", "checkout", "--detach", spec["sha"], cwd=destination)
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=destination, text=True).strip()
        if actual != spec["sha"]:
            raise RuntimeError(f"{package}: expected {spec['sha']}, got {actual}")
        print(f"{package} {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
