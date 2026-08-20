from pathlib import Path
import unittest

import yaml


HERE = Path(__file__).resolve().parent
QUESTION_ROOT = HERE.parents[1] / "docassemble" / "MATC1ADivorceJointPetition" / "data" / "questions"


def documents(filename: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all((QUESTION_ROOT / filename).read_text())
        if isinstance(document, dict)
    ]


def identified_code(filename: str, block_id: str) -> str:
    for document in documents(filename):
        if document.get("id") == block_id:
            return str(document.get("code", ""))
    raise AssertionError(f"missing code block {block_id}")


class CombinedSourceRegressionTests(unittest.TestCase):
    def test_uploaded_or_delayed_agreement_does_not_seek_built_agreement_state(self):
        order = identified_code("main_joint_petition.yml", "joint petition interview order")
        agreement_branch = order.split("if include_separation_agreement:", 1)[1].split(
            "# Findings and Determinations", 1
        )[0]
        self.assertNotIn("request_merge_agreement =", order)
        self.assertNotIn("request_survive_agreement =", order)
        self.assertIn("set_petition_merger_survival_values", agreement_branch)

        value_definitions = [
            document
            for document in documents("main_joint_petition.yml")
            if "petition_request_merge_agreement" in str(document.get("code", ""))
        ]
        self.assertEqual(len(value_definitions), 1)
        value_definition = str(value_definitions[0]["code"])
        self.assertIn("provisions_that_merge.all_false()", value_definition)
        self.assertIn(
            "petition_request_merge_agreement = request_merge_agreement",
            value_definition,
        )
        self.assertIn(
            "petition_request_survive_agreement = request_survive_agreement",
            value_definition,
        )

        petition = "\n".join(
            str(document)
            for document in documents("divorce_joint_petition.yml")
            if "request_merge_agreement" in str(document)
        )
        self.assertIn("${ petition_request_merge_agreement }", petition)
        self.assertIn("${ petition_request_survive_agreement }", petition)

    def test_r408_order_seeks_field_variables_not_question_ids(self):
        order = identified_code("r408_report_of_absolute_divorce.yml", "interview order r408")
        self.assertNotIn("\n    r408_demographics\n", order)
        self.assertNotIn("\n    r408_prior_marriages_and_birth_names\n", order)
        self.assertNotIn("\n    r408_additional_children_info\n", order)
        for variable in (
            "users1_gender",
            "users2_gender",
            "users1_ssn_last_four",
            "users2_ssn_last_four",
            "users1_marriage_number",
            "users2_marriage_number",
            "users1_name_last_at_birth",
            "users2_name_last_at_birth",
            "r408_addendum",
        ):
            self.assertIn(variable, order)

    def test_combined_parent_owns_fixed_count_child_details(self):
        child_questions = [
            document
            for document in documents("main_joint_petition.yml")
            if document.get("id") == "combined child details"
        ]
        self.assertEqual(len(child_questions), 1)
        question = child_questions[0]
        self.assertNotIn("list collect", question)
        self.assertIn("children[i].birthdate", str(question.get("fields", [])))

    def test_combined_motion_order_preserves_user_object_identity(self):
        joint_order = identified_code("main_joint_petition.yml", "joint petition interview order")
        combined_order = identified_code(
            "main_joint_petition.yml", "combined interview order motion to amend"
        )
        self.assertIn("combined_interview_order_motion_to_amend", joint_order)
        self.assertNotIn("\n  interview_order_motion_to_amend\n", joint_order)
        self.assertNotIn("users.elements[0]", combined_order)
        self.assertIn(
            "users[0].name.first, users[1].name.first = users[1].name.first, users[0].name.first",
            combined_order,
        )


if __name__ == "__main__":
    unittest.main()
