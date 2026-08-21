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
    def test_certification_snapshot_is_compact_and_bundle_evidence_precedes_generation(self):
        all_documents = documents("main_joint_petition.yml")
        snapshots = [
            document
            for document in all_documents
            if document.get("event") == "combined_certification_snapshot"
        ]
        self.assertEqual(len(snapshots), 1)
        snapshot = str(snapshots[0].get("code", ""))
        self.assertIn('action_argument("values")', snapshot)
        self.assertIn('action_argument("counts")', snapshot)
        self.assertIn("certification_value.as_serializable()", snapshot)
        self.assertIn("json_response(certification_snapshot)", snapshot)

        order_documents = [
            document
            for document in all_documents
            if document.get("mandatory") is True
            and "joint_petition_interview_order" in str(document.get("code", ""))
        ]
        self.assertEqual(len(order_documents), 1)
        order = str(order_documents[0]["code"])
        self.assertLess(
            order.index("combined_bundle_final_packet_normalized"),
            order.index("combined_bundle_enabled_document_names"),
        )
        self.assertLess(
            order.index("combined_bundle_enabled_document_names"),
            order.index("generate_downloads_with_docx_task"),
        )
        self.assertLess(
            order.index("combined_bundle_download_evidence"),
            order.index("divorcejointpetition_download", order.index("combined_bundle_download_evidence")),
        )
        bundle_names = identified_code(
            "main_joint_petition.yml", "combined bundle enabled document names"
        )
        self.assertIn("al_user_bundle.enabled_documents(refresh=True)", bundle_names)
        self.assertNotIn("del conditional_document.cache.enabled", bundle_names)
        final_normalization = identified_code(
            "main_joint_petition.yml", "combined bundle final packet normalization"
        )
        self.assertIn(
            "conditional_document.cache.enabled = bool(final_enabled)",
            final_normalization,
        )
        self.assertIn(
            "conditional_document.enabled = bool(final_enabled)",
            final_normalization,
        )
        self.assertNotIn("del conditional_document.cache.enabled", final_normalization)
        self.assertIn(
            "a_divorce_agreement_Post_interview_instructions,",
            final_normalization,
        )
        self.assertIn("include_separation_agreement,", final_normalization)
        self.assertIn(
            "combined_bundle_final_packet_normalized = True", final_normalization
        )
        download_evidence = identified_code(
            "main_joint_petition.yml", "combined bundle download evidence"
        )
        self.assertIn(
            "certification_document_results, certification_zip, certification_pdf = al_user_bundle._downloadable_files",
            download_evidence,
        )
        self.assertIn("combined_bundle_download_evidence", download_evidence)
        self.assertNotIn("combined_bundle_downloadable_files", order)

    def test_combined_parent_clears_standalone_document_enablement(self):
        order = identified_code("main_joint_petition.yml", "joint petition interview order")
        self.assertIn("combined_bundle_documents_normalized", order)
        normalization_blocks = [
            str(document.get("code", ""))
            for document in documents("main_joint_petition.yml")
            if "combined_bundle_documents_normalized = True" in str(document.get("code", ""))
        ]
        self.assertEqual(len(normalization_blocks), 1)
        normalization = normalization_blocks[0]
        self.assertIn('del conditional_document.cache.enabled', normalization)
        for document_name in (
            "motion_to_amend_attachment",
            "r408_attachment",
            "users[0].financial_statement_short_attachment",
            "users[1].financial_statement_long_attachment",
            "a_divorce_agreement_attachment",
            "affidavit_of_care_or_custody_attachment",
        ):
            self.assertIn(document_name, normalization)
        self.assertIn("conditional_document.always_enabled = False", normalization)

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
        self.assertEqual(
            set(question.get("sets", [])),
            {
                "children[i].name.first",
                "children[i].name.last",
                "children[i].name.middle",
                "children[i].name.suffix",
                "children[i].birthdate",
            },
        )

        petition_order = identified_code(
            "divorce_joint_petition.yml", "interview_order_divorcejointpetition"
        )
        self.assertLess(
            petition_order.index("children.ask_number = True"),
            petition_order.index("children.gather()"),
        )
        self.assertLess(
            petition_order.index(
                "children.target_number = children_of_marriage_number"
            ),
            petition_order.index("children.gather()"),
        )
        combined_order = identified_code(
            "main_joint_petition.yml", "joint petition interview order"
        )
        agreement_branch = combined_order.split(
            "if include_separation_agreement:", 1
        )[1]
        self.assertIn(
            "children.ask_number = True",
            agreement_branch,
        )
        self.assertIn(
            "children.target_number = children_of_marriage_number",
            agreement_branch,
        )
        self.assertNotIn("children.target_number = len(children)", agreement_branch)

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
