#!/usr/bin/env python3
"""Verify that a runtime used the exact declared image and external packages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def parse_freeze(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        result[name.lower()] = version
    return result


def freeze_digest(text: str) -> str:
    installed = parse_freeze(text)
    normalized = "".join(
        f"{name}=={version}\n" for name, version in sorted(installed.items())
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def verify(baseline: dict, image_digests: list[str], freeze_text: str) -> list[str]:
    errors = []
    expected_image = baseline["runtime"]["image"]
    if expected_image not in image_digests:
        errors.append(f"runtime image mismatch: expected {expected_image}, got {image_digests}")

    installed = parse_freeze(freeze_text)
    for package, expected_version in baseline["external_packages"].items():
        actual_version = installed.get(package.lower())
        if actual_version != expected_version:
            errors.append(
                f"package mismatch for {package}: expected {expected_version}, got {actual_version}"
            )
    expected_freeze_digest = baseline["runtime"].get("pip_freeze_sha256")
    actual_freeze_digest = freeze_digest(freeze_text)
    if expected_freeze_digest and actual_freeze_digest != expected_freeze_digest:
        errors.append(
            "pip freeze mismatch: "
            f"expected {expected_freeze_digest}, got {actual_freeze_digest}"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--pip-freeze", type=Path, required=True)
    args = parser.parse_args()

    errors = verify(
        json.loads(args.baseline.read_text()),
        json.loads(args.image.read_text()),
        args.pip_freeze.read_text(),
    )
    if errors:
        print("\n".join(errors))
        return 1
    print("runtime manifest matches baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
