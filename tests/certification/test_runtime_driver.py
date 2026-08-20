import unittest
from unittest.mock import patch

import requests

from runtime_driver import Limits, build_answer, run_scenario


SCENARIO = {
    "name": "fake",
    "interview": "docassemble.fake:data/questions/main.yml",
    "variables": {},
}


def limits(**overrides):
    values = {
        "request_timeout": 1,
        "scenario_timeout": 10,
        "max_steps": 10,
        "max_same_screen": 2,
        "max_same_state_visits": 2,
        "download_task_timeout": 5,
    }
    values.update(overrides)
    return Limits(**values)


class FakeClient:
    def __init__(self, questions):
        self.questions = iter(questions)

    def new_session(self, interview):
        return "session", "", interview

    def question(self, interview, session, secret):
        value = next(self.questions)
        if isinstance(value, Exception):
            raise value
        return value

    def answer(self, interview, session, secret, variables, event_list=None):
        return {}

    def delete(self, interview, session, secret):
        return None


class RuntimeDriverTests(unittest.TestCase):
    def test_string_false_show_if_value_keeps_visible_field(self):
        question = {
            "fields": [
                {"variable_name": "documented", "datatype": "boolean"},
                {
                    "variable_name": "format",
                    "datatype": "radio",
                    "choices": [{"label": "Later", "value": "wait"}],
                    "show_if_var": "documented",
                    "show_if_val": "False",
                },
            ]
        }
        answer = build_answer(question, {"documented": False, "format": "wait"})
        self.assertEqual(answer, {"documented": False, "format": "wait"})

    def test_consecutive_repeated_state_is_a_hang_failure(self):
        stuck = {
            "id": "same screen",
            "questionType": "question",
            "question_variable_name": "continue_here",
            "fields": [],
        }
        result = run_scenario(FakeClient([stuck, stuck, stuck]), SCENARIO, limits())
        self.assertEqual(result["failure"], "consecutive_repeated_state")

    def test_request_timeout_is_a_hang_failure(self):
        result = run_scenario(
            FakeClient([requests.Timeout("server stopped responding")]),
            SCENARIO,
            limits(),
        )
        self.assertEqual(result["failure"], "request_timeout")

    def test_error_screen_fails(self):
        error = {
            "id": "custom error action",
            "questionType": "deadend",
            "questionText": "There was an error",
            "subquestionText": "NameError: missing_variable",
        }
        result = run_scenario(FakeClient([error]), SCENARIO, limits())
        self.assertEqual(result["failure"], "error_screen")

    def test_undefined_variable_records_the_exact_name(self):
        error = {
            "questionType": "undefined_variable",
            "variable": "missing_variable",
            "message_log": [{"priority": "error", "message": "not defined"}],
        }
        result = run_scenario(FakeClient([error]), SCENARIO, limits())
        self.assertEqual(result["failure"], "error_screen")
        self.assertEqual(result["steps"][0]["undefined_variable"], "missing_variable")
        self.assertEqual(result["steps"][0]["message_log"][0]["priority"], "error")

    def test_download_screen_passes(self):
        terminal = {
            "id": "download divorce joint petition",
            "questionType": "event",
            "fields": [],
        }
        result = run_scenario(FakeClient([terminal]), SCENARIO, limits())
        self.assertEqual(result["status"], "pass")
        self.assertIsNone(result["failure"])

    def test_unexpected_normal_terminal_fails(self):
        terminal = {
            "id": "not the expected ending",
            "questionType": "deadend",
            "fields": [],
        }
        scenario = {**SCENARIO, "expected_terminal_ids": ["download divorce joint petition"]}
        result = run_scenario(FakeClient([terminal]), scenario, limits())
        self.assertEqual(result["failure"], "unexpected_terminal")

    @patch("runtime_driver.time.sleep", return_value=None)
    def test_download_waiting_screen_is_not_a_terminal_pass(self, _sleep):
        waiting = {
            "id": "waiting screen",
            "questionType": "event",
            "event_list": ["al_download_waiting_screen"],
            "fields": [],
        }
        terminal = {
            "id": "download divorce joint petition",
            "questionType": "event",
            "fields": [],
        }
        result = run_scenario(
            FakeClient([waiting, waiting, terminal]),
            SCENARIO,
            limits(max_steps=4),
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual([step["id"] for step in result["steps"]], [
            "waiting screen",
            "waiting screen",
            "download divorce joint petition",
        ])

    @patch("runtime_driver.time.monotonic", side_effect=[0, 0, 0, 6, 6])
    def test_download_waiting_screen_has_a_specific_timeout(self, _monotonic):
        waiting = {
            "id": "waiting screen",
            "questionType": "event",
            "event_list": ["al_download_waiting_screen"],
            "fields": [],
        }
        result = run_scenario(FakeClient([waiting]), SCENARIO, limits())
        self.assertEqual(result["failure"], "download_task_timeout")


if __name__ == "__main__":
    unittest.main()
