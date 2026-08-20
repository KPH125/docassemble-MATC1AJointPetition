#!/usr/bin/env python3
"""Build a deterministic static catalog for the combined 1A interview.

The catalog is one half of the coverage proof. Runtime traversal must account
for every reachable ID in this catalog and must separately record screens from
external packages that are only visible after Docassemble resolves includes.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def package_question_root(workspace: Path, package: str, spec: dict[str, Any]) -> Path:
    namespace = package.split(".", 1)[1]
    return workspace / spec["directory"] / "docassemble" / namespace / "data" / "questions"


def parse_interview_name(name: str) -> tuple[str | None, str]:
    if ":" not in name:
        return None, name
    package, relative = name.split(":", 1)
    prefix = "data/questions/"
    if relative.startswith(prefix):
        relative = relative[len(prefix) :]
    return package, relative


def field_variable(field: Any) -> str | None:
    if not isinstance(field, dict):
        return None
    metadata_keys = {
        "datatype", "choices", "required", "show if", "hide if", "help",
        "hint", "default", "code", "min", "max", "validation messages",
        "rows", "input type", "address autocomplete",
    }
    for key, value in field.items():
        if key not in metadata_keys and isinstance(value, str):
            return value
    return None


def choice_values(field: Any) -> list[Any]:
    if not isinstance(field, dict):
        return []
    choices = field.get("choices")
    if not isinstance(choices, list):
        return []
    result: list[Any] = []
    for choice in choices:
        if isinstance(choice, dict) and len(choice) == 1:
            result.append(next(iter(choice.values())))
        elif isinstance(choice, (str, int, float, bool)):
            result.append(choice)
    return result


def branch_expressions(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    expressions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            segment = ast.get_source_segment(code, node.test)
            if segment:
                expressions.add(" ".join(segment.split()))
    return sorted(expressions)


def document_kind(document: dict[str, Any]) -> str:
    for kind in ("question", "event", "code", "attachment", "attachments", "template", "objects"):
        if kind in document:
            return kind
    return "configuration"


def direct_question_variables(document: dict[str, Any]) -> list[str]:
    result = []
    for key in ("field", "yesno", "noyes", "signature", "dropdown", "combobox", "range"):
        value = document.get(key)
        if isinstance(value, str):
            result.append(value)
    return result


def screen_variant_signature(screen: dict[str, Any]) -> tuple[Any, ...]:
    normalize = lambda value: re.sub(r"\[\d+\]", "[i]", str(value or ""))
    return (
        screen["id"],
        screen.get("event"),
        normalize(screen.get("continue_button_field")),
        tuple(sorted(normalize(value) for value in screen.get("sets") or [])),
        tuple(sorted(normalize(value) for value in screen.get("variables") or [])),
    )


def iter_documents(path: Path) -> Iterable[dict[str, Any]]:
    for index, document in enumerate(yaml.safe_load_all(path.read_text()), start=1):
        if isinstance(document, dict):
            document = dict(document)
            document["_document_index"] = index
            yield document


def build_catalog(workspace: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    roots = {
        package: package_question_root(workspace, package, spec)
        for package, spec in baseline["packages"].items()
    }
    entry_package, entry_relative = parse_interview_name(baseline["entrypoint"])
    if entry_package is None:
        raise ValueError("The entrypoint must use a docassemble package name")
    feature_packages = set(baseline.get("coverage_scope", {}).get("feature_packages", []))
    framework_packages = set(baseline.get("coverage_scope", {}).get("framework_packages", []))
    if feature_packages | framework_packages != set(roots):
        raise ValueError("coverage_scope must classify every pinned package exactly once")
    if feature_packages & framework_packages:
        raise ValueError("coverage_scope package classifications must not overlap")

    pending: list[tuple[str, Path]] = [(entry_package, roots[entry_package] / entry_relative)]
    visited: set[Path] = set()
    unresolved: set[str] = set()
    files: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    screens: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []

    while pending:
        current_package, path = pending.pop()
        path = path.resolve()
        if path in visited:
            continue
        visited.add(path)
        if not path.exists():
            unresolved.add(f"{current_package}:{path.name}")
            continue

        file_record = {
            "package": current_package,
            "path": str(path.relative_to(workspace)),
            "documents": 0,
        }
        for document in iter_documents(path):
            file_record["documents"] += 1
            for include in document.get("include", []) or []:
                include_package, include_relative = parse_interview_name(str(include))
                if include_package is None:
                    pending.append((current_package, path.parent / include_relative))
                elif include_package in roots:
                    pending.append((include_package, roots[include_package] / include_relative))
                else:
                    unresolved.add(str(include))

            question_id = document.get("id")
            if question_id:
                fields = document.get("fields") or []
                block = {
                    "id": str(question_id),
                    "kind": document_kind(document),
                    "event": document.get("event"),
                    "mandatory": document.get("mandatory", False),
                    "sets": document.get("sets"),
                    "continue_button_field": document.get("continue button field"),
                    "package": current_package,
                    "coverage_scope": (
                        "combined_feature" if current_package in feature_packages else "framework_support"
                    ),
                    "path": file_record["path"],
                    "document_index": document["_document_index"],
                    "variables": direct_question_variables(document)
                    + [v for v in (field_variable(f) for f in fields) if v],
                    "choice_values": {
                        variable: choice_values(field)
                        for field in fields
                        if (variable := field_variable(field)) and choice_values(field)
                    },
                }
                blocks.append(block)
                if "question" in document or "event" in document:
                    screens.append(block)

            code = document.get("code")
            if isinstance(code, str):
                for expression in branch_expressions(code):
                    branches.append(
                        {
                            "expression": expression,
                            "package": current_package,
                            "path": file_record["path"],
                            "document_index": document["_document_index"],
                            "id": question_id,
                        }
                    )
        files.append(file_record)

    duplicate_ids: dict[str, list[str]] = {}
    for block in blocks:
        duplicate_ids.setdefault(block["id"], []).append(block["path"])
    duplicate_ids = {key: value for key, value in duplicate_ids.items() if len(value) > 1}

    return {
        "entrypoint": baseline["entrypoint"],
        "source_sha": baseline["source"]["sha"],
        "coverage_scope": baseline["coverage_scope"],
        "files": sorted(files, key=lambda item: item["path"]),
        "blocks": sorted(blocks, key=lambda item: (item["path"], item["document_index"])),
        "screens": sorted(screens, key=lambda item: (item["path"], item["document_index"])),
        "branches": sorted(branches, key=lambda item: (item["path"], item["document_index"], item["expression"])),
        "unresolved_external_includes": sorted(unresolved),
        "duplicate_ids": duplicate_ids,
        "counts": {
            "files": len(files),
            "identified_blocks": len(blocks),
            "unique_block_ids": len({block["id"] for block in blocks}),
            "screens": len(screens),
            "unique_screen_ids": len({screen["id"] for screen in screens}),
            "unique_screen_variants": len({screen_variant_signature(screen) for screen in screens}),
            "branch_expressions": len(branches),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    parser.add_argument("--workspace", type=Path, default=here.parents[2])
    parser.add_argument("--baseline", type=Path, default=here / "baseline.json")
    parser.add_argument("--output", type=Path, default=here / "static_catalog.json")
    args = parser.parse_args()

    catalog = build_catalog(args.workspace.resolve(), load_json(args.baseline))
    args.output.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    print(json.dumps(catalog["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
