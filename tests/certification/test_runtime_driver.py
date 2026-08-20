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
    def __init__(self, questions, actions=None):
        self.questions = iter(questions)
        self.actions = actions or {}
        self.pending_action = None

    def new_session(self, interview):
        return "session", "", interview

    def question(self, interview, session, secret):
        if self.pending_action:
            value = self.actions[self.pending_action]
            self.pending_action = None
        else:
            value = next(self.questions)
        if isinstance(value, Exception):
            raise value
        return value

    def answer(
        self,
        interview,
        session,
        secret,
        variables,
        event_list=None,
        question_name=None,
    ):
        return {}

    def variables(self, interview, session, secret):
        return {"divorcejointpetition_downloads_ready": True}

    def action(self, interview, session, secret, action, arguments=None):
        self.pending_action = action

    def delete(self, interview, session, secret):
        return None


class RuntimeDriverTests(unittest.TestCase):
    def test_settrue_field_defaults_to_boolean_true(self):
        question = {
            "questionType": "settrue",
            "fields": [{"variable_name": "intro_complete", "datatype": "text"}],
        }
        self.assertEqual(build_answer(question, {}), {"intro_complete": True})

    def test_ssn_fields_use_a_valid_representative(self):
        question = {
            "fields": [{"variable_name": "users[0].ssn", "datatype": "ssn"}],
        }
        self.assertEqual(
            build_answer(question, {}),
            {"users[0].ssn": "123-45-6789"},
        )

    def test_string_false_show_if_value_keeps_visible_field(self):
        question = {
            "fields": [
                {"variable_name": "documented", "datatype": "boolean"},
                {
                    "variable_name": "format",
                    "datatype": "radio",
                    "choices": [{"label": "Upload", "value": "upload"}],
                    "show_if_var": "documented",
                    "show_if_val": "True",
                },
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

    def test_expression_show_if_does_not_hide_server_visible_fields(self):
        question = {
            "fields": [
                {
                    "variable_name": "users1_gender",
                    "datatype": "text",
                    "inputtype": "radio",
                    "choices": [{"label": "Male", "value": "male"}],
                    "show_if_var": 'not showifdef("users1_gender")',
                    "show_if_val": "True",
                }
            ],
        }
        self.assertEqual(build_answer(question, {}), {"users1_gender": "male"})

    def test_unmodeled_list_controls_default_to_no(self):
        question = {
            "fields": [{
                "variable_name": "children[0].previous_addresses.there_is_another",
                "datatype": "yesnoradio",
            }]
        }
        self.assertEqual(
            build_answer(question, {}),
            {"children[0].previous_addresses.there_is_another": False},
        )

    def test_index_normalized_modeled_answer_applies_to_each_list_member(self):
        question = {
            "fields": [{
                "variable_name": "children[2].previous_addresses.there_are_any",
                "datatype": "yesnoradio",
            }]
        }
        self.assertEqual(
            build_answer(question, {"children[i].previous_addresses.there_are_any": True}),
            {"children[2].previous_addresses.there_are_any": True},
        )

    def test_modeled_sequence_controls_repeated_list_answers(self):
        question = {
            "fields": [{
                "variable_name": "items.there_is_another",
                "datatype": "yesnoradio",
            }]
        }
        positions = {}
        variables = {"items.there_is_another": {"$sequence": [True, False]}}
        self.assertEqual(build_answer(question, variables, positions), {"items.there_is_another": True})
        self.assertEqual(build_answer(question, variables, positions), {"items.there_is_another": False})
        with self.assertRaisesRegex(ValueError, "sequence exhausted"):
            build_answer(question, variables, positions)

    def test_code_button_uses_the_diversion_event_variable(self):
        question = {
            "id": "warning",
            "questionType": "multiple_choice",
            "event_list": ["warning_acknowledged"],
            "fields": [],
        }
        self.assertEqual(
            build_answer(question, {}),
            {"warning_acknowledged": True},
        )

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
        self.assertTrue(result["terminal_evidence"]["divorcejointpetition_downloads_ready"])

    def test_unexpected_normal_terminal_fails(self):
        terminal = {
            "id": "not the expected ending",
            "questionType": "deadend",
            "fields": [],
        }
        scenario = {**SCENARIO, "expected_terminal_ids": ["download divorce joint petition"]}
        result = run_scenario(FakeClient([terminal]), scenario, limits())
        self.assertEqual(result["failure"], "unexpected_terminal")

    def test_terminal_bundle_evidence_mismatch_fails(self):
        terminal = {
            "id": "download divorce joint petition",
            "questionType": "event",
            "fields": [],
        }
        scenario = {
            **SCENARIO,
            "expected_terminal_evidence": {"include_financial_statement": True},
        }
        result = run_scenario(FakeClient([terminal]), scenario, limits())
        self.assertEqual(result["failure"], "terminal_evidence_mismatch")
        self.assertEqual(
            result["terminal_evidence_mismatches"]["include_financial_statement"],
            {"expected": True, "observed": "<missing>"},
        )

    def test_declared_event_probe_adds_its_screen_to_coverage(self):
        terminal = {
            "id": "download divorce joint petition",
            "questionType": "event",
            "fields": [],
        }
        review = {
            "id": "divorce joint petition review screen",
            "questionType": "review",
            "fields": [],
        }
        scenario = {
            **SCENARIO,
            "probe_events": [{
                "event": "review_divorcejointpetition",
                "expected_id": "divorce joint petition review screen",
            }],
        }
        result = run_scenario(
            FakeClient([terminal], {"review_divorcejointpetition": review}),
            scenario,
            limits(),
        )
        self.assertEqual(result["status"], "pass")
        self.assertIn("divorce joint petition review screen", result["seen_screen_ids"])

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
