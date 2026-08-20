#!/usr/bin/env python3
"""Drive modeled paths through Docassemble and emit a machine-readable ledger.

This is intentionally strict. Unknown runtime states, error screens, repeated
states, request timeouts, wall-clock timeouts, and step exhaustion are failures.
It is the runtime half of the combined-interview coverage proof.
"""

from __future__ import annotations

import argparse
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
import yaml


HERE = Path(__file__).resolve().parent


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def question_id(question: dict[str, Any]) -> str:
    return str(question.get("id") or question.get("questionName") or "<unnamed>")


def question_variable(question: dict[str, Any]) -> str:
    return str(
        question.get("question_variable_name")
        or question.get("continue_button_field")
        or question.get("continueButtonField")
        or ""
    )


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


def resolve_generic(variable: str, sought: str) -> str:
    if not variable.startswith(("x.", "x[")) or not sought:
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


def answer_for_field(field: dict[str, Any], resolved: str, variables: dict[str, Any]) -> Any:
    if resolved in variables:
        value = variables[resolved]
    elif field["variable"] in variables:
        value = variables[field["variable"]]
    elif field["datatype"] == "file":
        value = ""
    elif field["datatype"] == "checkboxes":
        value = {}
    elif field["choices"]:
        value = first_choice(field["choices"])
    else:
        value = DEFAULTS.get(str(field["inputtype"]), DEFAULTS.get(str(field["datatype"]), "Test"))
    if field["datatype"] == "checkboxes":
        return serialized_checkboxes(resolved, field["choices"], value)
    return value


def show_if_matches(actual: Any, expected: Any) -> bool:
    if expected is None:
        return bool(actual)
    if isinstance(actual, (bool, int, float)) or isinstance(expected, (bool, int, float)):
        return str(actual).lower() == str(expected).lower()
    return actual == expected


def build_answer(question: dict[str, Any], scenario_variables: dict[str, Any]) -> dict[str, Any]:
    sought = question_variable(question)
    answer: dict[str, Any] = {}
    fields = field_info(question)
    for field in fields:
        raw = field["variable"]
        resolved = resolve_generic(raw, sought)
        send_name = raw if raw.startswith(("x.", "x[")) else resolved
        answer[send_name] = answer_for_field(field, resolved, scenario_variables)

    # Do not submit fields hidden by a simple same-screen show-if condition.
    for field in fields:
        controller = field.get("show_if_var")
        if not controller:
            continue
        raw = field["variable"]
        resolved = resolve_generic(raw, sought)
        send_name = raw if raw.startswith(("x.", "x[")) else resolved
        controller_value = answer.get(controller)
        expected = field.get("show_if_val")
        visible = show_if_matches(controller_value, expected)
        if not visible:
            answer.pop(send_name, None)

    field_names = {
        resolve_generic(field["variable"], sought)
        for field in fields
    } | {field["variable"] for field in fields}
    if sought and sought not in field_names:
        answer[sought] = scenario_variables.get(sought, True)
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

    def answer(
        self,
        interview: str,
        session: str,
        secret: str,
        variables: dict[str, Any],
        event_list: list[str] | None = None,
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
        for step_number in range(1, limits.max_steps + 1):
            if time.monotonic() - started > limits.scenario_timeout:
                result["failure"] = "scenario_timeout"
                break
            question = client.question(interview, session, secret)
            qid = question_id(question)
            fingerprint = question_fingerprint(question)
            state_visits[fingerprint] = state_visits.get(fingerprint, 0) + 1
            consecutive = consecutive + 1 if fingerprint == previous_state else 1
            previous_state = fingerprint
            step = {
                "number": step_number,
                "id": qid,
                "type": question.get("questionType"),
                "fingerprint": fingerprint,
                "variant_fingerprint": screen_variant_fingerprint(question),
                "sought": question_variable(question),
                "fields": field_info(question),
                "event_list": question.get("event_list") or [],
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
            if consecutive > limits.max_same_screen:
                result["failure"] = "consecutive_repeated_state"
                break
            if state_visits[fingerprint] > limits.max_same_state_visits:
                result["failure"] = "revisited_state_loop"
                break
            if is_terminal(question):
                result["terminal_id"] = qid
                expected_terminal_ids = set(scenario.get("expected_terminal_ids", []))
                if expected_terminal_ids and qid not in expected_terminal_ids:
                    result["failure"] = "unexpected_terminal"
                    result["expected_terminal_ids"] = sorted(expected_terminal_ids)
                else:
                    result["status"] = "pass"
                    result["failure"] = None
                break

            answer = build_answer(question, variables)
            step["answer"] = answer
            response = client.answer(
                interview,
                session,
                secret,
                answer,
                question.get("event_list") or [],
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
    model = yaml.safe_load(model_path.read_text())
    policy = model["hang_policy"]
    return Limits(
        request_timeout=int(policy["request_timeout_seconds"]),
        scenario_timeout=int(policy["scenario_timeout_seconds"]),
        max_steps=int(policy["max_steps"]),
        max_same_screen=int(policy["max_same_screen_consecutive"]),
        max_same_state_visits=int(policy["max_same_state_visits"]),
        download_task_timeout=int(policy["download_task_timeout_seconds"]),
    )


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
    client = Client(args.server, args.api_key, limits.request_timeout)
    scenarios = [json.loads(path.read_text()) for path in sorted(args.scenarios.glob("*.json"))]
    results = [run_scenario(client, scenario, limits) for scenario in scenarios]
    ledger = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "server": args.server,
        "results": results,
        "summary": {
            "scenarios": len(results),
            "passed": sum(result["status"] == "pass" for result in results),
            "failed": sum(result["status"] != "pass" for result in results),
            "unique_screen_ids": len({screen for result in results for screen in result["seen_screen_ids"]}),
        },
    }
    args.ledger.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    print(json.dumps(ledger["summary"], sort_keys=True))
    for result in results:
        print(f"{result['status'].upper()} {result['name']}: {result.get('failure') or result.get('terminal_id')}")
    return 1 if ledger["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
