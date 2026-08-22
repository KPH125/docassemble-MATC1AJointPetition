from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from docassemble.MATC1ADivorceJointPetition.clinic_workspace import DOCUMENT_REGISTRY


ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "docassemble" / "MATC1ADivorceJointPetition" / "data" / "questions"


class ClinicSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard_source = (QUESTIONS / "main_clinic_dashboard.yml").read_text()
        cls.matter_source = (QUESTIONS / "main_student_packet.yml").read_text()
        cls.pro_se_source = (QUESTIONS / "main_joint_petition.yml").read_text()
        cls.temporary_orders_source = (QUESTIONS / "temporary_orders_packet.yml").read_text()

    def test_new_yaml_files_parse(self) -> None:
        self.assertGreater(len(list(yaml.safe_load_all(self.dashboard_source))), 1)
        self.assertGreater(len(list(yaml.safe_load_all(self.matter_source))), 1)

    def test_dynamic_field_attributes_use_docassemble_code_syntax(self) -> None:
        self.assertNotIn("required: ${", self.matter_source)

    def test_embedded_python_blocks_compile(self) -> None:
        for filename, source in (
            ("main_clinic_dashboard.yml", self.dashboard_source),
            ("main_student_packet.yml", self.matter_source),
        ):
            for document_number, document in enumerate(
                yaml.safe_load_all(source), start=1
            ):
                if not isinstance(document, dict):
                    continue
                for block_name in ("code", "validation code"):
                    block = document.get(block_name)
                    if isinstance(block, str):
                        with self.subTest(
                            filename=filename,
                            document=document_number,
                            block=block_name,
                        ):
                            compile(block, f"{filename}:{document_number}:{block_name}", "exec")

    def test_staff_entrypoints_require_login_and_clinic_privileges(self) -> None:
        for source in (self.dashboard_source, self.matter_source):
            self.assertIn("require login: True", source)
            self.assertIn("clinic_student", source)
            self.assertIn("clinic_supervisor", source)
            self.assertIn("clinic_admin", source)

    def test_client_and_signer_are_not_platform_privileges(self) -> None:
        metadata_prefix = self.matter_source.split("---\nmodules:", 1)[0]
        self.assertNotIn("client\n", metadata_prefix)
        self.assertNotIn("signer\n", metadata_prefix)

    def test_pro_se_and_temporary_orders_mandatory_flows_are_guarded(self) -> None:
        guard = 'if not showifdef("clinic_workspace_mode", False):'
        self.assertIn(guard, self.pro_se_source)
        self.assertIn(guard, self.temporary_orders_source)

    def test_clinic_mode_is_initialized_before_child_includes(self) -> None:
        mode_position = self.matter_source.index("clinic_workspace_mode = True")
        include_position = self.matter_source.index("include:")
        self.assertLess(mode_position, include_position)
        self.assertIn("template: interview_short_title", self.matter_source)
        self.assertIn("Clinic 1A divorce workspace", self.matter_source)

    def test_new_matter_is_created_only_after_the_filing_plan_is_answered(self) -> None:
        mandatory = self.matter_source.split("mandatory: True", 1)[1]
        self.assertLess(
            mandatory.index("clinic_document_planner"),
            mandatory.index("clinic_matter = new_matter("),
        )

    def test_every_registry_document_has_a_planner_choice_and_workflow_controller(self) -> None:
        for document_id, definition in DOCUMENT_REGISTRY.items():
            with self.subTest(document_id=document_id):
                self.assertIn(f": {document_id}", self.matter_source)
                self.assertIn(
                    f"sets: {definition['workflow_event']}", self.matter_source
                )

    def test_dashboard_listing_is_assigned_user_scoped_except_for_clinic_admin(self) -> None:
        repository_source = (
            ROOT
            / "docassemble"
            / "MATC1ADivorceJointPetition"
            / "clinic_repository.py"
        ).read_text()
        self.assertIn('user_id="all" if can_list_all else user_info().id', repository_source)
        self.assertIn('global_search_allowed_roles={"clinic_admin"}', repository_source)
        self.assertNotIn('user_id="all",', repository_source)

    def test_received_file_does_not_claim_automatic_answer_import(self) -> None:
        self.assertIn(
            "The file will not change answers or enter a bundle",
            self.matter_source,
        )
        self.assertNotIn("ocr_file", self.matter_source)

    def test_operational_lifecycle_actions_are_exposed(self) -> None:
        for event in (
            "clinic_manage_team",
            "clinic_assign_document",
            "clinic_begin_review",
            "clinic_begin_verify_artifact",
            "clinic_transition_execution",
            "clinic_build_bundle",
            "clinic_begin_close_matter",
        ):
            with self.subTest(event=event):
                self.assertIn(f"event: {event}", self.matter_source)
        self.assertEqual(
            self.matter_source.count("clinic_bundle_return_to_matter = True"),
            2,
        )
        self.assertNotIn("- Return to matter: restart", self.matter_source)

    def test_direct_file_and_document_events_enforce_matter_access(self) -> None:
        documents = list(yaml.safe_load_all(self.matter_source))
        event_documents = {
            document["event"]: document.get("code", "")
            for document in documents
            if isinstance(document, dict) and "event" in document
        }
        workflow_documents = {
            document["sets"]: document.get("code", "")
            for document in documents
            if isinstance(document, dict)
            and str(document.get("sets", "")).startswith("clinic_work_")
        }
        self.assertIn(
            "can_view_matter",
            event_documents["clinic_build_bundle"],
        )
        for definition in DOCUMENT_REGISTRY.values():
            with self.subTest(event=definition["workflow_event"]):
                self.assertIn(
                    "can_edit_facts",
                    workflow_documents[definition["workflow_event"]],
                )

    def test_generated_versions_are_frozen_before_they_enter_history(self) -> None:
        self.assertIn("snapshot_generated_artifact(", self.matter_source)
        self.assertIn("clinic_generated_files", self.matter_source)
        self.assertNotIn('"generated_draft",\n    user_info().id', self.matter_source)

    def test_existing_generated_documents_route_to_review_screens(self) -> None:
        self.assertIn(
            'url_action("clinic_begin_document_answer_review", document_id=document_id)',
            self.matter_source,
        )
        self.assertIn("continue button field: clinic_document_answer_review_screen", self.matter_source)
        self.assertIn('"undefine": [entry["variable"]]', self.matter_source)
        self.assertIn("sets: clinic_record_document_answer_review", self.matter_source)
        review_route = self.matter_source.split(
            "event: clinic_begin_document_answer_review", 1
        )[1].split("---", 1)[0]
        self.assertNotIn("redirect(", review_route)
        self.assertIn('document_id=document_id, regenerate=True', self.matter_source)
        self.assertIn("Review or update answers", self.matter_source)
        self.assertIn("Regenerate draft", self.matter_source)

    def test_dashboard_is_the_only_fresh_matter_entry_route(self) -> None:
        self.assertIn('url_args.get("clinic_create", "0")', self.matter_source)
        self.assertIn("redirect(\n      interview_url(", self.matter_source)
        self.assertIn("new_session=1, clinic_create=1", self.dashboard_source)

    def test_dashboard_has_distinct_first_use_and_filtered_empty_states(self) -> None:
        self.assertIn("No clinic matters yet", self.dashboard_source)
        self.assertIn("Create your first matter", self.dashboard_source)
        self.assertIn("No matters need review", self.dashboard_source)
        self.assertIn("No closed matters", self.dashboard_source)
        self.assertIn("View all matters", self.dashboard_source)
        self.assertIn('force_ask("clinic_dashboard_home")', self.dashboard_source)

    def test_clinic_parent_owns_navigation_and_progress(self) -> None:
        self.assertIn("navigation: True", self.matter_source)
        self.assertIn("small screen navigation: dropdown", self.matter_source)
        self.assertIn("clinic_navigation_sections = [", self.matter_source)
        self.assertIn("clinic_document_questions: Questions and draft", self.matter_source)
        self.assertIn('nav.set_section("clinic_document_questions")', self.matter_source)
        self.assertIn('url_action("clinic_return_to_matter")', self.matter_source)
        self.assertIn("This measures work recorded in the clinic workspace", self.matter_source)
        guard = 'if not showifdef("clinic_workspace_mode", False):'
        for source in (self.pro_se_source, self.temporary_orders_source):
            for line_number, line in enumerate(source.splitlines()):
                if "nav.set_section(" not in line:
                    continue
                previous_line = source.splitlines()[line_number - 1].strip()
                self.assertEqual(previous_line, guard)
        navigation_controller = self.matter_source.split(
            'url_args.get("clinic_create", "0")', 1
        )[1].split("mandatory: True", 1)[0]
        self.assertIn(
            'nav.set_sections(clinic_navigation_sections, language="en")',
            navigation_controller,
        )
        self.assertIn(
            'nav.set_sections(clinic_navigation_sections, language="*")',
            navigation_controller,
        )
        self.assertLess(
            navigation_controller.index("nav.set_sections(clinic_navigation_sections)"),
            navigation_controller.index("process_action()"),
        )

    def test_document_work_persists_until_the_generator_finishes(self) -> None:
        self.assertNotIn("id: clinic main order", self.matter_source)
        self.assertIn(
            'clinic_current_summary = persist_current_matter_summary(clinic_matter)\n'
            '  # Keep this controller live across every workspace request.',
            self.matter_source,
        )
        self.assertIn('force_ask("clinic_workspace_home")', self.matter_source)
        self.assertNotIn("clinic_main_order = True", self.matter_source)
        self.assertIn(
            'if showifdef("clinic_document_work_in_progress", False):',
            self.matter_source,
        )
        self.assertIn(
            'undefine(DOCUMENT_REGISTRY[clinic_active_document_id]["workflow_event"])',
            self.matter_source,
        )
        workflow_documents = {
            document["sets"]: document.get("code", "")
            for document in yaml.safe_load_all(self.matter_source)
            if isinstance(document, dict)
            and str(document.get("sets", "")).startswith("clinic_work_")
        }
        for definition in DOCUMENT_REGISTRY.values():
            with self.subTest(event=definition["workflow_event"]):
                self.assertIn(
                    "clinic_document_work_in_progress = False",
                    workflow_documents[definition["workflow_event"]],
                )
                self.assertIn(
                    f'{definition["workflow_event"]} = True',
                    workflow_documents[definition["workflow_event"]],
                )

    def test_r408_missing_details_screen_always_exposes_its_fields(self) -> None:
        r408_source = (
            ROOT
            / "docassemble"
            / "MATC1ADivorceJointPetition"
            / "data"
            / "questions"
            / "r408_report_of_absolute_divorce.yml"
        ).read_text()
        question = r408_source.split("id: r408 prior marriages and birth names", 1)[1]
        question = question.split("---", 1)[0]
        self.assertNotIn("show if:", question)

    def test_multistep_workspace_actions_use_the_durable_pending_controller(self) -> None:
        self.assertIn(
            'if showifdef("clinic_pending_action", None):', self.matter_source
        )
        for record_id in (
            "clinic_apply_edited_plan",
            "clinic_record_matter_details",
            "clinic_record_received_file",
            "clinic_record_review_decision",
            "clinic_record_artifact_verification",
            "clinic_record_team_member",
            "clinic_record_internal_note",
            "clinic_record_document_assignment",
            "clinic_record_document_answer_review",
            "clinic_record_matter_close",
        ):
            with self.subTest(record_id=record_id):
                self.assertIn(
                    f'clinic_pending_action = "{record_id}"', self.matter_source
                )
                self.assertIn(f"sets: {record_id}", self.matter_source)
                self.assertIn(f"  {record_id} = True", self.matter_source)
        for screen_id, record_id in (
            ("clinic_document_planner", "clinic_apply_edited_plan"),
            ("clinic_matter_details_screen", "clinic_record_matter_details"),
            ("clinic_received_file_screen", "clinic_record_received_file"),
            ("clinic_review_decision_screen", "clinic_record_review_decision"),
            ("clinic_team_member_screen", "clinic_record_team_member"),
            ("clinic_internal_note_screen", "clinic_record_internal_note"),
            (
                "clinic_document_answer_review_screen",
                "clinic_record_document_answer_review",
            ),
            ("clinic_close_matter_screen", "clinic_record_matter_close"),
        ):
            with self.subTest(screen_id=screen_id):
                self.assertIn(
                    f'force_ask("{screen_id}", "{record_id}")',
                    self.matter_source,
                )
        self.assertGreaterEqual(self.matter_source.count("clinic_pending_action = None"), 9)


if __name__ == "__main__":
    unittest.main()
