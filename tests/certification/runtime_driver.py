#!/usr/bin/env python3
"""Drive modeled paths through Docassemble and emit a machine-readable ledger.

This is intentionally strict. Unknown runtime states, error screens, repeated
states, request timeouts, wall-clock timeouts, and step exhaustion are failures.
It is the runtime half of the combined-interview coverage proof.
"""

from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from model_loader import load_model


HERE = Path(__file__).resolve().parent


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def question_id(question: dict[str, Any]) -> str:
    return str(question.get("id") or question.get("questionName") or "<unnamed>")


def question_source_file(question: dict[str, Any], interview: str) -> str:
    """Return a compact, stable locator for the question's interview file."""
    source = question.get("source")
    if isinstance(source, dict):
        history = source.get("history")
        if isinstance(history, dict) and history.get("source_file"):
            return str(history["source_file"])
    # Docassemble omits source_file for questions defined by the root
    # interview, so the resolved interview name is the authoritative fallback.
    return interview


def question_variable(question: dict[str, Any]) -> str:
    direct = str(
        question.get("question_variable_name")
        or question.get("continue_button_field")
        or question.get("continueButtonField")
        or ""
    )
    if direct:
        return direct
    # For reusable questions whose source fields contain ``[i]``, the API
    # exposes the concrete variable being sought in ``event_list`` even when
    # it omits question_variable_name. That concrete name is authoritative for
    # resolving the iterator before submitting the answer.
    events = question.get("event_list") or []
    return str(events[0]) if events else ""


def question_fingerprint(question: dict[str, Any]) -> str:
    fields = []
    for field in question.get("fields", []) or []:
        fields.append(
            {
                "variable": field.get("variable_name") or field.get("variable"),
                "datatype": field.get("datatype"),
                "inputtype": field.get("inputtype"),
                "choices": field.get("choices"),
            }
        )
    payload = {
        "id": question_id(question),
        "type": question.get("questionType"),
        "variable": question_variable(question),
        "fields": fields,
        "event_list": question.get("event_list"),
    }
    return hashlib.sha256(canonical(payload).encode()).hexdigest()[:16]


def normalized_variable(value: Any) -> str:
    return re.sub(r"\[\d+\]", "[i]", str(value or ""))


def screen_variant_fingerprint(question: dict[str, Any]) -> str:
    fields = [
        {
            "variable": normalized_variable(field.get("variable_name") or field.get("variable")),
            "datatype": field.get("datatype"),
            "inputtype": field.get("inputtype"),
        }
        for field in question.get("fields", []) or []
    ]
    payload = {
        "id": question_id(question),
        "type": question.get("questionType"),
        "variable": normalized_variable(question_variable(question)),
        "fields": fields,
    }
    return hashlib.sha256(canonical(payload).encode()).hexdigest()[:16]


def display_text(question: dict[str, Any]) -> str:
    return " ".join(
        str(question.get(key, ""))
        for key in ("questionText", "question", "subquestionText", "subquestion")
    ).lower()


def is_error(question: dict[str, Any]) -> bool:
    text = display_text(question)
    markers = (
        "there was an error", "an error occurred", "internal server error",
        "traceback", "nameerror", "attributeerror", "typeerror", "keyerror",
        "indexerror", "maximum recursion", "infinite loop",
    )
    if any(marker in text for marker in markers):
        return True
    return question.get("questionType") == "undefined_variable"


def is_terminal(question: dict[str, Any]) -> bool:
    qid = question_id(question).lower()
    qtype = str(question.get("questionType", "")).lower()
    if qtype in {"exit", "restart", "deadend"}:
        return True
    if "download" in qid and not question.get("fields"):
        return True
    return False


def is_download_waiting_screen(question: dict[str, Any]) -> bool:
    qid = question_id(question).lower()
    events = {str(item).lower() for item in question.get("event_list", []) or []}
    return qid == "waiting screen" or "al_download_waiting_screen" in events


def serialized_collection_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        elements = value.get("elements")
        if isinstance(elements, (list, dict)):
            return len(elements)
    return None


def serialized_path_cardinality(root: dict[str, Any], path: str) -> int | list[int] | None:
    """Count a serialized collection at a dotted path, with ``[*]`` fan-out."""
    values: list[Any] = [root]
    used_wildcard = False
    parts = path.split(".")
    for part_index, part in enumerate(parts):
        match = re.fullmatch(r"([^\[]+)(?:\[(\*|\d+)\])?", part)
        if not match:
            return None
        name, index = match.groups()
        next_values: list[Any] = []
        for container in values:
            if not isinstance(container, dict) or name not in container:
                # A missing nested collection on an existing wildcard parent
                # is Docassemble's serialized representation of an empty
                # optional list. Preserve that parent as cardinality zero.
                if used_wildcard and part_index == len(parts) - 1:
                    next_values.append([])
                continue
            value = container[name]
            if index is None:
                next_values.append(value)
                continue
            elements = value.get("elements") if isinstance(value, dict) else value
            if index == "*":
                used_wildcard = True
                if isinstance(elements, list):
                    next_values.extend(elements)
                elif isinstance(elements, dict):
                    next_values.extend(elements.values())
            elif isinstance(elements, list) and int(index) < len(elements):
                next_values.append(elements[int(index)])
            elif isinstance(elements, dict) and index in elements:
                next_values.append(elements[index])
        values = next_values
    counts = [
        count
        for value in values
        if (count := serialized_collection_count(value)) is not None
    ]
    if used_wildcard:
        return counts
    return counts[0] if counts else None


def serialized_path_value(root: dict[str, Any], path: str) -> Any:
    """Return a value from Docassemble's nested serialized object format."""
    value: Any = root
    for part in path.split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        if not match or not isinstance(value, dict):
            return None
        name, index = match.groups()
        if name not in value:
            return None
        value = value[name]
        if index is not None:
            elements = value.get("elements") if isinstance(value, dict) else value
            if isinstance(elements, list) and int(index) < len(elements):
                value = elements[int(index)]
            elif isinstance(elements, dict) and index in elements:
                value = elements[index]
            else:
                return None
    return value


def field_within_cardinalities(
    variable: str,
    expected_cardinalities: dict[str, dict[str, Any]] | None,
) -> bool:
    """Reject rendered list-collect rows beyond the scenario's finite model."""
    concrete_parts = [
        re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        for part in variable.split(".")
    ]
    if any(part is None for part in concrete_parts):
        return True
    concrete = [(part.group(1), part.group(2)) for part in concrete_parts if part]
    for probe in (expected_cardinalities or {}).values():
        expected = probe["expected"]
        probe_parts = [
            re.fullmatch(r"([^\[]+)(?:\[(\*)\])?", part)
            for part in probe["variable"].split(".")
        ]
        if any(part is None for part in probe_parts) or len(concrete) < len(probe_parts):
            continue
        wildcard_indexes: list[int] = []
        matches = True
        for position, part in enumerate(probe_parts):
            assert part is not None
            name, wildcard = part.groups()
            concrete_name, concrete_index = concrete[position]
            if name != concrete_name:
                matches = False
                break
            if wildcard:
                if concrete_index is None:
                    matches = False
                    break
                wildcard_indexes.append(int(concrete_index))
        if not matches:
            continue
        element_index = concrete[len(probe_parts) - 1][1]
        if element_index is None:
            continue
        if isinstance(expected, list):
            if not wildcard_indexes or wildcard_indexes[-1] >= len(expected):
                return False
            limit = int(expected[wildcard_indexes[-1]])
        else:
            limit = int(expected)
        if int(element_index) >= limit:
            return False
    return True


def resolve_generic(variable: str, sought: str) -> str:
    if not sought:
        return variable
    if "[i]" in variable:
        generic_root = variable.split("[i]", 1)[0]
        index_match = re.search(rf"^{re.escape(generic_root)}\[(\d+)\]", sought)
        if index_match:
            return variable.replace("[i]", f"[{index_match.group(1)}]", 1)
    if not variable.startswith(("x.", "x[")):
        return variable
    object_name = re.split(r"[.[]", sought, maxsplit=1)[0]
    index_match = re.search(r"\[(\d+)\]", sought)
    if variable.startswith("x[i]") and index_match:
        return f"{object_name}[{index_match.group(1)}]{variable[4:]}"
    return object_name + variable[1:]


def field_info(question: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for field in question.get("fields", []) or []:
        datatype = field.get("datatype", "text")
        if datatype in {"note", "html", "raw"}:
            continue
        variable = field.get("variable_name") or field.get("variable") or ""
        if not variable:
            continue
        result.append(
            {
                "variable": str(variable),
                "datatype": datatype,
                "inputtype": field.get("inputtype") or field.get("input type") or datatype,
                "choices": field.get("choices") or [],
                "required": field.get("required", True),
                "show_if_var": field.get("show_if_var") or "",
                "show_if_val": field.get("show_if_val"),
            }
        )
    return result


DEFAULTS = {
    "text": "Test",
    "area": "Test details",
    "email": "test@example.com",
    "tel": "6175550100",
    "phone": "6175550100",
    "ssn": "123-45-6789",
    "date": "2025-01-15",
    "integer": 1,
    "number": 1,
    "currency": 100,
    "yesno": True,
    "yesnoradio": True,
    "yesnowide": True,
    "boolean": True,
    "noyes": False,
    "noyesradio": False,
    "noyeswide": False,
    "yesnomaybe": False,
    "noyesmaybe": False,
    "threestate": False,
    "signature": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
}


def first_choice(choices: list[Any]) -> Any:
    if not choices:
        return None
    choice = choices[0]
    if isinstance(choice, dict):
        return choice.get("value", choice.get("label", next(iter(choice.values()), None)))
    if isinstance(choice, list):
        return choice[0] if choice else None
    return choice


def serialized_checkboxes(resolved: str, choices: list[Any], selected: Any) -> dict[str, Any]:
    selected = selected if isinstance(selected, dict) else {}
    elements: dict[str, bool] = {}
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        variable = str(choice.get("variable_name", ""))
        match = re.search(r"\['([^']+)'\]", variable)
        key = match.group(1) if match else choice.get("value")
        if key is not None:
            elements[str(key)] = bool(selected.get(str(key), False))
    if not elements:
        elements = {str(key): bool(value) for key, value in selected.items()}
    return {
        "_class": "docassemble.base.util.DADict",
        "instanceName": resolved,
        "elements": elements,
        "auto_gather": False,
        "gathered": True,
    }


def serialized_object_choices(
    resolved: str,
    choices: list[Any],
    selected: Any,
    current_variables: dict[str, Any] | None,
) -> dict[str, Any]:
    """Serialize selected object references as the DAList expected by the API."""
    if isinstance(selected, dict):
        selected_names = [str(key) for key, value in selected.items() if value]
    elif isinstance(selected, (list, tuple, set)):
        selected_names = [str(value) for value in selected]
    elif selected in (None, False, ""):
        selected_names = []
    else:
        selected_names = [str(selected)]

    available = {
        str(choice.get("value")): choice
        for choice in choices
        if isinstance(choice, dict) and choice.get("value") is not None
    }
    unknown = [name for name in selected_names if name not in available]
    if unknown:
        raise ValueError(f"object selection for {resolved} contains unknown choices: {unknown}")
    if current_variables is None:
        raise ValueError(f"object selection for {resolved} requires current session variables")

    template = serialized_path_value(current_variables, resolved)
    if isinstance(template, dict) and template.get("_class"):
        result = copy.deepcopy(template)
    else:
        result = {
            "_class": "docassemble.base.util.DAList",
            "instanceName": resolved,
        }
    elements = []
    for name in selected_names:
        source = serialized_path_value(current_variables, name)
        if not isinstance(source, dict) or not source.get("_class"):
            raise ValueError(f"object choice {name} is absent from current session variables")
        elements.append(copy.deepcopy(source))
    result.update(
        {
            "elements": elements,
            "auto_gather": False,
            "gathered": True,
            "there_are_any": bool(elements),
            "there_is_another": False,
        }
    )
    return result


def scenario_value(
    variables: dict[str, Any],
    resolved: str,
    raw: str,
    sequence_positions: dict[str, int] | None = None,
) -> tuple[bool, Any]:
    """Return an exact or index-normalized modeled answer.

    ``$sequence`` values let a scenario answer repeated list controls such as
    ``there_is_another`` deterministically. Exhaustion is an error: silently
    repeating the last value could conceal an unexpected traversal loop.
    """
    for key in dict.fromkeys((resolved, raw, normalized_variable(resolved), normalized_variable(raw))):
        if key not in variables:
            continue
        value = variables[key]
        if isinstance(value, dict) and set(value) == {"$sequence"}:
            sequence = value["$sequence"]
            if not isinstance(sequence, list) or not sequence:
                raise ValueError(f"modeled answer sequence for {key} must be a non-empty list")
            positions = sequence_positions if sequence_positions is not None else {}
            position = positions.get(key, 0)
            if position >= len(sequence):
                raise ValueError(f"modeled answer sequence exhausted for {key}")
            positions[key] = position + 1
            return True, sequence[position]
        return True, value
    return False, None


def answer_for_field(
    field: dict[str, Any],
    resolved: str,
    variables: dict[str, Any],
    sequence_positions: dict[str, int] | None = None,
    current_variables: dict[str, Any] | None = None,
) -> Any:
    found, value = scenario_value(
        variables,
        resolved,
        field["variable"],
        sequence_positions,
    )
    if found:
        pass
    elif field["datatype"] in {"object_checkboxes", "object_multiselect"}:
        first = first_choice(field["choices"])
        value = [] if first is None else [first]
    elif field["datatype"] == "file":
        value = ""
    elif field["datatype"] == "checkboxes":
        value = {}
    elif normalized_variable(resolved).endswith((".there_are_any", ".there_is_another")):
        # Empty is the safe representative for a list unless the scenario
        # explicitly claims a one-or-many cardinality.
        value = False
    elif field["choices"]:
        value = first_choice(field["choices"])
    else:
        value = DEFAULTS.get(str(field["inputtype"]), DEFAULTS.get(str(field["datatype"]), "Test"))
    if field["datatype"] == "checkboxes":
        return serialized_checkboxes(resolved, field["choices"], value)
    if field["datatype"] in {"object_checkboxes", "object_multiselect"}:
        return serialized_object_choices(
            resolved,
            field["choices"],
            value,
            current_variables,
        )
    return value


def show_if_matches(actual: Any, expected: Any) -> bool:
    if expected is None:
        return bool(actual)
    if isinstance(actual, (bool, int, float)) or isinstance(expected, (bool, int, float)):
        return str(actual).lower() == str(expected).lower()
    return actual == expected


def build_answer(
    question: dict[str, Any],
    scenario_variables: dict[str, Any],
    sequence_positions: dict[str, int] | None = None,
    expected_cardinalities: dict[str, dict[str, Any]] | None = None,
    current_variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sought = question_variable(question)
    answer: dict[str, Any] = {}
    fields = field_info(question)
    field_values: dict[str, Any] = {}
    for field in fields:
        raw = field["variable"]
        resolved = resolve_generic(raw, sought)
        if not field_within_cardinalities(resolved, expected_cardinalities):
            continue
        send_name = raw if raw.startswith(("x.", "x[")) else resolved
        if question.get("questionType") == "settrue":
            answer[send_name] = scenario_variables.get(
                resolved, scenario_variables.get(raw, True)
            )
        else:
            if send_name not in field_values:
                field_values[send_name] = answer_for_field(
                    field,
                    resolved,
                    scenario_variables,
                    sequence_positions,
                    current_variables,
                )
            answer[send_name] = field_values[send_name]

    # Do not submit fields hidden by a simple same-screen show-if condition.
    # A screen can declare multiple conditional variants of the same variable;
    # keep the variable if at least one of those variants is visible.
    hidden_names: set[str] = set()
    visible_names: set[str] = set()
    for field in fields:
        controller = resolve_generic(str(field.get("show_if_var") or ""), sought)
        # The API can expose a Python expression (for example,
        # ``not showifdef("users1_gender")``) in show_if_var. We can safely
        # evaluate only a controller that is another submitted field on this
        # screen. Unknown or expression-based controllers stay visible so the
        # server, not the driver, remains the authority on their condition.
        if not controller or controller not in answer:
            continue
        raw = field["variable"]
        resolved = resolve_generic(raw, sought)
        send_name = raw if raw.startswith(("x.", "x[")) else resolved
        controller_value = answer.get(controller)
        expected = field.get("show_if_val")
        visible = show_if_matches(controller_value, expected)
        (visible_names if visible else hidden_names).add(send_name)
    for send_name in hidden_names - visible_names:
        answer.pop(send_name, None)

    field_names = {
        resolve_generic(field["variable"], sought)
        for field in fields
    } | {field["variable"] for field in fields}
    if sought and sought not in field_names:
        answer[sought] = scenario_variables.get(sought, True)
    if question.get("questionType") == "multiple_choice" and not fields:
        # A code-button screen has no ordinary field. Its event list identifies
        # the variable whose definition diverted interview logic to this
        # screen; the first button in our modeled warnings is the continue
        # action that sets that variable true.
        for event_name in question.get("event_list", []) or []:
            answer[str(event_name)] = scenario_variables.get(str(event_name), True)
    if not answer:
        normalized_id = question_id(question).replace(" ", "_").replace("-", "_")
        answer[normalized_id] = scenario_variables.get(normalized_id, True)
    return answer


@dataclass
class Limits:
    request_timeout: int
    scenario_timeout: int
    max_steps: int
    max_same_screen: int
    max_same_state_visits: int
    download_task_timeout: int


class Client:
    def __init__(self, server: str, api_key: str, timeout: int):
        self.server = server.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.http = requests.Session()

    def _params(self, interview: str, session: str, secret: str = "") -> dict[str, Any]:
        result = {"key": self.api_key, "i": interview, "session": session}
        if secret:
            result["secret"] = secret
        return result

    def new_session(self, interview: str) -> tuple[str, str, str]:
        response = self.http.get(
            f"{self.server}/api/session/new",
            params={"key": self.api_key, "i": interview},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["session"], data.get("secret", ""), data.get("i", interview)

    def question(self, interview: str, session: str, secret: str) -> dict[str, Any]:
        response = self.http.get(
            f"{self.server}/api/session/question",
            params=self._params(interview, session, secret),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def variables(self, interview: str, session: str, secret: str) -> dict[str, Any]:
        response = self.http.get(
            f"{self.server}/api/session",
            params=self._params(interview, session, secret),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def answer(
        self,
        interview: str,
        session: str,
        secret: str,
        variables: dict[str, Any],
        event_list: list[str] | None = None,
        question_name: str | None = None,
    ) -> dict[str, Any]:
        payload = self._params(interview, session, secret)
        uploads = {
            name: value["$file"]
            for name, value in variables.items()
            if isinstance(value, dict) and "$file" in value
        }
        ordinary_variables = {name: value for name, value in variables.items() if name not in uploads}
        payload["variables"] = canonical(ordinary_variables)
        if event_list:
            payload["event_list"] = canonical(event_list)
        if question_name:
            payload["question_name"] = question_name
        with ExitStack() as stack:
            files = {
                name: stack.enter_context(open((HERE.parents[1] / relative).resolve(), "rb"))
                for name, relative in uploads.items()
            }
            response = self.http.post(
                f"{self.server}/api/session",
                data=payload,
                files=files or None,
                timeout=self.timeout,
            )
        response.raise_for_status()
        return response.json()

    def action(
        self,
        interview: str,
        session: str,
        secret: str,
        action: str,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        payload = self._params(interview, session, secret)
        payload.update(
            {
                "action": action,
                "persistent": 1,
                "arguments": canonical(arguments or {}),
            }
        )
        response = self.http.post(
            f"{self.server}/api/session/action",
            data=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()

    def delete(self, interview: str, session: str, secret: str) -> None:
        try:
            self.http.delete(
                f"{self.server}/api/session",
                data=self._params(interview, session, secret),
                timeout=min(self.timeout, 10),
            )
        except requests.RequestException:
            pass


def run_scenario(client: Client, scenario: dict[str, Any], limits: Limits) -> dict[str, Any]:
    started = time.monotonic()
    interview = scenario["interview"]
    variables = scenario.get("variables", {})
    result: dict[str, Any] = {
        "name": scenario["name"],
        "interview": interview,
        "status": "fail",
        "failure": None,
        "steps": [],
        "seen_screen_ids": [],
    }
    session = secret = ""
    try:
        session, secret, interview = client.new_session(interview)
        state_visits: dict[str, int] = {}
        previous_state = ""
        consecutive = 0
        download_wait_started: float | None = None
        sequence_positions: dict[str, int] = {}
        for step_number in range(1, limits.max_steps + 1):
            if time.monotonic() - started > limits.scenario_timeout:
                result["failure"] = "scenario_timeout"
                break
            question = client.question(interview, session, secret)
            qid = question_id(question)
            fingerprint = question_fingerprint(question)
            step = {
                "number": step_number,
                "id": qid,
                "type": question.get("questionType"),
                "question_keys": sorted(question),
                "fingerprint": fingerprint,
                "variant_fingerprint": screen_variant_fingerprint(question),
                "sought": question_variable(question),
                "fields": field_info(question),
                "event_list": question.get("event_list") or [],
                "question_name": question.get("questionName"),
                "source_file": question_source_file(question, interview),
                "mandatory": bool(question.get("mandatory")),
            }
            if question.get("questionType") == "undefined_variable":
                step["undefined_variable"] = question.get("variable")
            if question.get("message_log"):
                step["message_log"] = question.get("message_log")
            result["steps"].append(step)
            if qid not in result["seen_screen_ids"]:
                result["seen_screen_ids"].append(qid)

            if is_error(question):
                result["failure"] = "error_screen"
                step["text"] = display_text(question)[:1000]
                break
            if is_download_waiting_screen(question):
                if download_wait_started is None:
                    download_wait_started = time.monotonic()
                waited = time.monotonic() - download_wait_started
                step["download_wait_seconds"] = round(waited, 3)
                if waited > limits.download_task_timeout:
                    result["failure"] = "download_task_timeout"
                    break
                time.sleep(2)
                continue
            download_wait_started = None
            if is_terminal(question):
                result["terminal_id"] = qid
                expected_terminal_ids = set(scenario.get("expected_terminal_ids", []))
                if expected_terminal_ids and qid not in expected_terminal_ids:
                    result["failure"] = "unexpected_terminal"
                    result["expected_terminal_ids"] = sorted(expected_terminal_ids)
                else:
                    terminal_variables = client.variables(interview, session, secret)
                    evidence_names = (
                        "al_user_bundle",
                        "divorcejointpetition_downloads_ready",
                        "include_r408",
                        "include_care_or_custody_affidavit",
                        "include_financial_statement",
                        "include_financial_statement_spouse_1",
                        "include_financial_statement_spouse_2",
                        "include_separation_agreement",
                        "include_child_support_guidelines_worksheet",
                        "include_findings_and_determinations",
                        "needs_late_marriage_certificate_motion",
                    )
                    result["terminal_evidence"] = {
                        name: terminal_variables[name]
                        for name in evidence_names
                        if name in terminal_variables
                    }
                    result["cardinality_evidence"] = {}
                    cardinality_mismatches = {}
                    for name, probe in scenario.get("expected_cardinalities", {}).items():
                        variable_name = probe["variable"]
                        if variable_name in terminal_variables:
                            observed_count = serialized_collection_count(
                                terminal_variables[variable_name]
                            )
                        else:
                            observed_count = serialized_path_cardinality(
                                terminal_variables,
                                variable_name,
                            )
                        result["cardinality_evidence"][name] = {
                            "variable": variable_name,
                            "expected": probe["expected"],
                            "observed": observed_count,
                        }
                        if observed_count is None and probe["expected"] in (0, []):
                            observed_count = copy.deepcopy(probe["expected"])
                            result["cardinality_evidence"][name]["observed"] = observed_count
                        if observed_count != probe["expected"]:
                            cardinality_mismatches[name] = result["cardinality_evidence"][name]
                    if cardinality_mismatches:
                        result["failure"] = "cardinality_evidence_mismatch"
                        result["cardinality_evidence_mismatches"] = cardinality_mismatches
                        break
                    expected_evidence = scenario.get("expected_terminal_evidence", {})
                    evidence_mismatches = {
                        name: {
                            "expected": expected,
                            "observed": result["terminal_evidence"].get(name, "<missing>"),
                        }
                        for name, expected in expected_evidence.items()
                        if result["terminal_evidence"].get(name, "<missing>") != expected
                    }
                    if evidence_mismatches:
                        result["failure"] = "terminal_evidence_mismatch"
                        result["terminal_evidence_mismatches"] = evidence_mismatches
                        break
                    result["event_probes"] = []
                    for probe in scenario.get("probe_events", []):
                        client.action(
                            interview,
                            session,
                            secret,
                            probe["event"],
                            probe.get("arguments"),
                        )
                        probe_question = client.question(interview, session, secret)
                        probe_id = question_id(probe_question)
                        probe_result = {
                            "event": probe["event"],
                            "id": probe_id,
                            "type": probe_question.get("questionType"),
                        }
                        result["event_probes"].append(probe_result)
                        if probe_id not in result["seen_screen_ids"]:
                            result["seen_screen_ids"].append(probe_id)
                        if is_error(probe_question):
                            result["failure"] = "event_probe_error"
                            probe_result["text"] = display_text(probe_question)[:1000]
                            break
                        if probe_id != probe["expected_id"]:
                            result["failure"] = "unexpected_event_probe_screen"
                            probe_result["expected_id"] = probe["expected_id"]
                            break
                    else:
                        result["status"] = "pass"
                        result["failure"] = None
                break

            needs_current_variables = any(
                field["datatype"] in {"object_checkboxes", "object_multiselect"}
                and field_within_cardinalities(
                    resolve_generic(field["variable"], question_variable(question)),
                    scenario.get("expected_cardinalities"),
                )
                for field in field_info(question)
            )
            current_variables = (
                client.variables(interview, session, secret)
                if needs_current_variables
                else None
            )
            answer = build_answer(
                question,
                variables,
                sequence_positions,
                scenario.get("expected_cardinalities"),
                current_variables,
            )
            step["answer"] = answer
            # A repeated list-control screen is legitimate when a declared
            # sequence is advancing. Include the answer and sequence cursor in
            # the state identity so finite modeled traversal is not mistaken
            # for a hang; an unchanged state still fails quickly, and an
            # unexpected extra repetition exhausts the declared sequence.
            state_payload = {
                "question": fingerprint,
                "answer": answer,
                "sequence_positions": sequence_positions,
            }
            state_fingerprint = hashlib.sha256(
                canonical(state_payload).encode()
            ).hexdigest()[:16]
            step["state_fingerprint"] = state_fingerprint
            state_visits[state_fingerprint] = state_visits.get(state_fingerprint, 0) + 1
            consecutive = consecutive + 1 if state_fingerprint == previous_state else 1
            previous_state = state_fingerprint
            if consecutive > limits.max_same_screen:
                result["failure"] = "consecutive_repeated_state"
                break
            if state_visits[state_fingerprint] > limits.max_same_state_visits:
                result["failure"] = "revisited_state_loop"
                break
            response = client.answer(
                interview,
                session,
                secret,
                answer,
                question.get("event_list") or [],
                question.get("questionName") if question.get("mandatory") else None,
            )
            if is_error(response):
                result["failure"] = "error_after_answer"
                step["response"] = response
                break
        else:
            result["failure"] = "max_steps_exhausted"
    except requests.Timeout as exc:
        result["failure"] = "request_timeout"
        result["exception"] = str(exc)
    except requests.RequestException as exc:
        result["failure"] = "http_error"
        result["exception"] = str(exc)
        if getattr(exc, "response", None) is not None:
            result["response"] = exc.response.text[:2000]
    except Exception as exc:  # strict ledger: unexpected harness errors also fail
        result["failure"] = "driver_exception"
        result["exception"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if session:
            client.delete(interview, session, secret)
    return result


def load_limits(model_path: Path) -> Limits:
    model = load_model(model_path)
    policy = model["hang_policy"]
    return Limits(
        request_timeout=int(policy["request_timeout_seconds"]),
        scenario_timeout=int(policy["scenario_timeout_seconds"]),
        max_steps=int(policy["max_steps"]),
        max_same_screen=int(policy["max_same_screen_consecutive"]),
        max_same_state_visits=int(policy["max_same_state_visits"]),
        download_task_timeout=int(policy["download_task_timeout_seconds"]),
    )


def write_ledger(path: Path, server: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    ledger = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "server": server,
        "results": results,
        "summary": {
            "scenarios": len(results),
            "passed": sum(result["status"] == "pass" for result in results),
            "failed": sum(result["status"] != "pass" for result in results),
            "unique_screen_ids": len({
                screen
                for result in results
                for screen in result["seen_screen_ids"]
            }),
        },
    }
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=os.environ.get("DA_SERVER_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("DA_API_KEY", ""))
    parser.add_argument("--scenarios", type=Path, default=HERE / "scenarios")
    parser.add_argument("--model", type=Path, default=HERE / "coverage_model.yml")
    parser.add_argument("--ledger", type=Path, default=HERE / "runtime_ledger.json")
    args = parser.parse_args()
    if not args.server or not args.api_key:
        parser.error("--server and --api-key (or DA_SERVER_URL/DA_API_KEY) are required")

    limits = load_limits(args.model)
    model = load_model(args.model)
    workers = int(model["hang_policy"].get("runtime_workers", 1))
    if workers < 1:
        parser.error("hang_policy.runtime_workers must be at least 1")
    scenarios = [json.loads(path.read_text()) for path in sorted(args.scenarios.glob("*.json"))]
    indexed_results: dict[int, dict[str, Any]] = {}

    def run_indexed(index: int, scenario: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        client = Client(args.server, args.api_key, limits.request_timeout)
        return index, run_scenario(client, scenario, limits)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_indexed, index, scenario)
            for index, scenario in enumerate(scenarios)
        ]
        for future in as_completed(futures):
            index, result = future.result()
            indexed_results[index] = result
            print(
                f"{result['status'].upper()} {result['name']}: "
                f"{result.get('failure') or result.get('terminal_id')}",
                flush=True,
            )
            write_ledger(
                args.ledger,
                args.server,
                [indexed_results[item] for item in sorted(indexed_results)],
            )

    results = [indexed_results[index] for index in range(len(scenarios))]
    ledger = write_ledger(args.ledger, args.server, results)
    print(json.dumps(ledger["summary"], sort_keys=True))
    return 1 if ledger["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
