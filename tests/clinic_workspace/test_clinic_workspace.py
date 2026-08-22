from __future__ import annotations

import unittest
from datetime import datetime, timezone

from docassemble.MATC1ADivorceJointPetition.clinic_workspace import (
    DOCUMENT_REGISTRY,
    ClinicWorkspaceError,
    add_internal_note,
    add_artifact,
    affected_documents_for_change,
    assign_document,
    assert_safe_metadata,
    assign_team_member,
    bundle_artifacts,
    can_edit_facts,
    can_manage_team,
    can_review_document,
    can_view_matter,
    close_matter,
    clinic_document_review_entries,
    deactivate_team_member,
    filter_visible_summaries,
    mark_fact_changes,
    matter_workflow_progress,
    new_matter,
    normalize_safe_label,
    record_review_decision,
    reassign_matter_owner,
    safe_matter_summary,
    set_artifact_disposition,
    set_bundle_destination,
    set_document_plan,
    transition_execution,
    transition_review,
    verify_artifact,
)


NOW = datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)


class MatterModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matter = new_matter(101, "MAT-2026-0042", matter_id="matter-42", now=NOW)

    def test_new_matter_has_every_supported_document(self) -> None:
        self.assertIn("joint_petition", self.matter["documents"])
        self.assertIn("temporary_orders_packet", self.matter["documents"])
        self.assertIn("financial_statement_party_a", self.matter["documents"])
        self.assertIn("financial_statement_party_b", self.matter["documents"])

    def test_workflow_progress_explains_each_counted_milestone(self) -> None:
        set_document_plan(self.matter, "joint_petition", "prepare_now", 101, now=NOW)
        self.assertEqual(
            matter_workflow_progress(self.matter),
            {
                "percent": 10,
                "selected": 1,
                "with_current_file": 0,
                "approved": 0,
                "executed": 0,
            },
        )
        artifact = add_artifact(
            self.matter,
            "joint_petition",
            "generated_draft",
            101,
            file_reference="clinic_generated_files[0]",
            now=NOW,
        )
        self.assertEqual(matter_workflow_progress(self.matter)["percent"], 70)
        transition_review(self.matter, "joint_petition", "ready_for_review", 101, now=NOW)
        record_review_decision(
            self.matter,
            "joint_petition",
            "approved",
            202,
            now=NOW,
        )
        self.assertEqual(matter_workflow_progress(self.matter)["percent"], 90)
        artifact["verified_at"] = NOW.isoformat()
        self.matter["documents"]["joint_petition"]["execution_status"] = "signed"
        self.assertEqual(matter_workflow_progress(self.matter)["percent"], 99)
        close_matter(self.matter, 202, reason="administrative", now=NOW)
        self.assertEqual(matter_workflow_progress(self.matter)["percent"], 100)

    def test_every_supported_document_has_clinic_owned_answer_review(self) -> None:
        missing = [
            document_id
            for document_id in DOCUMENT_REGISTRY
            if not clinic_document_review_entries(document_id)
        ]
        self.assertEqual(missing, [])

    def test_financial_answer_review_uses_concrete_party_indices(self) -> None:
        party_a_variables = {
            entry["variable"]
            for entry in clinic_document_review_entries("financial_statement_party_a")
        }
        party_b_variables = {
            entry["variable"]
            for entry in clinic_document_review_entries("financial_statement_party_b")
        }
        self.assertIn("users[0].income_list.revisit", party_a_variables)
        self.assertIn("users[1].income_list.revisit", party_b_variables)
        self.assertFalse(any("[i]" in variable for variable in party_a_variables))
        self.assertFalse(any("[i]" in variable for variable in party_b_variables))

    def test_safe_summary_does_not_copy_confidential_matter_fields(self) -> None:
        self.matter["client_name"] = "Do Not Index"
        self.matter["documents"]["joint_petition"]["private_note"] = "Do Not Index"
        add_internal_note(self.matter, "Confidential team note", 101, now=NOW)
        summary = safe_matter_summary(self.matter)
        self.assertEqual(summary["safe_label"], "MAT-2026-0042")
        self.assertNotIn("client_name", summary)
        self.assertNotIn("documents", summary)
        self.assertNotIn("internal_notes", summary)

    def test_safe_metadata_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ClinicWorkspaceError):
            assert_safe_metadata({"matter_id": "x", "client_name": "Unsafe"})

    def test_safe_label_rejects_markup_and_path_characters(self) -> None:
        for label in ("<script>", "MAT/0001", "MAT\\0001"):
            with self.subTest(label=label), self.assertRaises(ClinicWorkspaceError):
                normalize_safe_label(label)

    def test_dependencies_are_visible_before_review(self) -> None:
        set_document_plan(
            self.matter, "findings_and_determinations", "prepare_now", 101, now=NOW
        )
        item = self.matter["documents"]["findings_and_determinations"]
        self.assertEqual(item["dependency_blockers"], ["child_support_guidelines"])
        transition_review(self.matter, "findings_and_determinations", "in_progress", 101, now=NOW)
        with self.assertRaises(ClinicWorkspaceError):
            transition_review(
                self.matter,
                "findings_and_determinations",
                "ready_for_review",
                101,
                now=NOW,
            )

    def test_reference_upload_does_not_advance_execution(self) -> None:
        artifact = add_artifact(
            self.matter,
            "separation_agreement",
            "existing_reference",
            101,
            file_reference="clinic_received_files[0]",
            now=NOW,
        )
        item = self.matter["documents"]["separation_agreement"]
        self.assertEqual(item["source_status"], "uploaded_reference")
        self.assertEqual(item["execution_status"], "draft")
        self.assertFalse(artifact["eligible_for_bundle"])

    def test_received_working_draft_can_be_reviewed_without_regeneration(self) -> None:
        artifact = add_artifact(
            self.matter,
            "separation_agreement",
            "external_working_draft",
            101,
            now=NOW,
        )
        item = self.matter["documents"]["separation_agreement"]
        self.assertEqual(item["source_status"], "external_working_draft")
        self.assertEqual(item["review_status"], "in_progress")
        self.assertEqual(artifact["revision"], 0)

    def test_received_file_disposition_can_route_to_regeneration(self) -> None:
        artifact = add_artifact(
            self.matter,
            "separation_agreement",
            "client_annotated_reference",
            101,
            now=NOW,
        )
        set_artifact_disposition(
            self.matter,
            "separation_agreement",
            artifact["artifact_id"],
            "update_answers_and_regenerate",
            101,
            now=NOW,
        )
        self.assertEqual(artifact["intake_disposition"], "update_answers_and_regenerate")
        self.assertEqual(
            self.matter["documents"]["separation_agreement"]["review_status"],
            "in_progress",
        )

    def test_supervisor_change_request_requires_a_comment(self) -> None:
        item = self.matter["documents"]["joint_petition"]
        item["review_status"] = "ready_for_review"
        with self.assertRaises(ClinicWorkspaceError):
            record_review_decision(
                self.matter,
                "joint_petition",
                "changes_requested",
                202,
                now=NOW,
            )
        record_review_decision(
            self.matter,
            "joint_petition",
            "changes_requested",
            202,
            comment="Correct the separation date.",
            now=NOW,
        )
        self.assertEqual(item["review_history"][-1]["comment"], "Correct the separation date.")

    def test_document_without_a_current_file_cannot_enter_review(self) -> None:
        item = self.matter["documents"]["joint_petition"]
        item["review_status"] = "in_progress"
        with self.assertRaises(ClinicWorkspaceError):
            transition_review(
                self.matter,
                "joint_petition",
                "ready_for_review",
                101,
                now=NOW,
            )

    def test_approved_current_artifact_can_enter_court_bundle(self) -> None:
        set_document_plan(self.matter, "joint_petition", "prepare_now", 101, now=NOW)
        set_bundle_destination(
            self.matter, "joint_petition", "court_use", True, 101, now=NOW
        )
        artifact = add_artifact(
            self.matter,
            "joint_petition",
            "generated_draft",
            101,
            file_reference="joint_petition.pdf",
            now=NOW,
        )
        transition_review(self.matter, "joint_petition", "ready_for_review", 101, now=NOW)
        record_review_decision(
            self.matter, "joint_petition", "approved", 202, now=NOW
        )
        self.assertTrue(artifact["eligible_for_bundle"])
        self.assertEqual(bundle_artifacts(self.matter, "court_use"), [artifact])

    def test_superseded_artifact_is_not_bundle_eligible(self) -> None:
        set_document_plan(self.matter, "joint_petition", "prepare_now", 101, now=NOW)
        set_bundle_destination(
            self.matter, "joint_petition", "court_use", True, 101, now=NOW
        )
        first = add_artifact(
            self.matter,
            "joint_petition",
            "generated_draft",
            101,
            file_reference="joint_petition-v1.pdf",
            now=NOW,
        )
        first["eligible_for_bundle"] = True
        first["eligible_bundle_types"] = ["court_use", "records"]
        second = add_artifact(
            self.matter,
            "joint_petition",
            "generated_draft",
            101,
            file_reference="joint_petition-v2.pdf",
            supersedes_artifact_id=first["artifact_id"],
            now=NOW,
        )
        second["eligible_for_bundle"] = True
        second["eligible_bundle_types"] = ["court_use", "records"]
        self.assertFalse(first["eligible_for_bundle"])
        self.assertEqual(bundle_artifacts(self.matter, "court_use"), [second])

    def test_signed_claim_requires_verification_to_advance_status(self) -> None:
        artifact = add_artifact(
            self.matter, "joint_petition", "signed_copy", 101, now=NOW
        )
        self.assertEqual(
            self.matter["documents"]["joint_petition"]["execution_status"], "draft"
        )
        verify_artifact(
            self.matter, "joint_petition", artifact["artifact_id"], 202, now=NOW
        )
        self.assertEqual(
            self.matter["documents"]["joint_petition"]["execution_status"], "signed"
        )

    def test_changed_facts_invalidate_approval_and_execution(self) -> None:
        item = self.matter["documents"]["joint_petition"]
        artifact = add_artifact(
            self.matter,
            "joint_petition",
            "generated_draft",
            101,
            file_reference="joint-petition.pdf",
            now=NOW,
        )
        item["review_status"] = "approved"
        item["execution_status"] = "signed"
        artifact["eligible_for_bundle"] = True
        artifact["eligible_bundle_types"] = ["court_use", "records"]
        mark_fact_changes(self.matter, ["joint_petition"], 101, now=NOW)
        self.assertEqual(item["review_status"], "in_progress")
        self.assertEqual(item["execution_status"], "needs_revision")
        self.assertFalse(artifact["eligible_for_bundle"])
        self.assertEqual(artifact["eligible_bundle_types"], [])

    def test_filed_copy_remains_records_only_after_fact_change(self) -> None:
        artifact = add_artifact(
            self.matter,
            "joint_petition",
            "filed_copy",
            101,
            file_reference="filed-copy.pdf",
            now=NOW,
        )
        verify_artifact(
            self.matter, "joint_petition", artifact["artifact_id"], 202, now=NOW
        )
        mark_fact_changes(self.matter, ["joint_petition"], 101, now=NOW)
        self.assertEqual(artifact["eligible_bundle_types"], ["records"])

    def test_rejected_court_return_creates_revision_blocker_and_records_artifact(self) -> None:
        artifact = add_artifact(
            self.matter,
            "joint_petition",
            "court_returned_copy",
            101,
            file_reference="rejected-return.pdf",
            details={"court_outcome": "rejected", "court_note": "Correct caption"},
            now=NOW,
        )
        verify_artifact(
            self.matter, "joint_petition", artifact["artifact_id"], 202, now=NOW
        )
        item = self.matter["documents"]["joint_petition"]
        self.assertEqual(item["execution_status"], "needs_revision")
        self.assertEqual(artifact["eligible_bundle_types"], ["records"])

    def test_shared_fact_change_identifies_selected_dependent_documents(self) -> None:
        for document_id in (
            "financial_statement_party_a",
            "child_support_guidelines",
            "findings_and_determinations",
            "separation_agreement",
        ):
            set_document_plan(self.matter, document_id, "prepare_now", 101, now=NOW)
        affected = affected_documents_for_change(
            self.matter, "financial_statement_party_a"
        )
        self.assertEqual(
            set(affected),
            {
                "financial_statement_party_a",
                "child_support_guidelines",
                "findings_and_determinations",
                "separation_agreement",
            },
        )

    def test_signature_requires_approved_revision(self) -> None:
        item = self.matter["documents"]["joint_petition"]
        item["review_status"] = "in_progress"
        with self.assertRaises(ClinicWorkspaceError):
            transition_execution(
                self.matter, "joint_petition", "ready_for_signature", 101, now=NOW
            )
        item["review_status"] = "approved"
        transition_execution(
            self.matter, "joint_petition", "ready_for_signature", 101, now=NOW
        )
        self.assertEqual(item["execution_status"], "ready_for_signature")

    def test_completed_closeout_rejects_unfinished_planned_document(self) -> None:
        set_document_plan(self.matter, "joint_petition", "prepare_now", 101, now=NOW)
        with self.assertRaises(ClinicWorkspaceError):
            close_matter(self.matter, 202, reason="completed", now=NOW)
        close_matter(self.matter, 202, reason="withdrawn", now=NOW)
        self.assertEqual(self.matter["closure_reason"], "withdrawn")


class AccessPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matter = new_matter(101, "MAT-2026-0042", matter_id="matter-42", now=NOW)
        assign_team_member(self.matter, 202, "supervisor", 101, now=NOW)
        assign_team_member(self.matter, 303, "collaborator", 101, now=NOW)

    def test_unauthenticated_or_unprivileged_user_cannot_view(self) -> None:
        self.assertFalse(can_view_matter(self.matter, 101, []))
        self.assertFalse(can_view_matter(self.matter, 101, ["user"]))

    def test_unrelated_student_cannot_view(self) -> None:
        self.assertFalse(can_view_matter(self.matter, 999, ["clinic_student"]))

    def test_assigned_staff_can_view(self) -> None:
        self.assertTrue(can_view_matter(self.matter, 101, ["clinic_student"]))
        self.assertTrue(can_view_matter(self.matter, 202, ["clinic_supervisor"]))
        self.assertTrue(can_view_matter(self.matter, 303, ["clinic_student"]))

    def test_only_student_workers_edit_facts(self) -> None:
        self.assertTrue(can_edit_facts(self.matter, 101, ["clinic_student"]))
        self.assertTrue(can_edit_facts(self.matter, 303, ["clinic_student"]))
        self.assertFalse(can_edit_facts(self.matter, 202, ["clinic_supervisor"]))

    def test_only_assigned_supervisor_reviews(self) -> None:
        self.assertTrue(
            can_review_document(self.matter, 202, ["clinic_supervisor"])
        )
        self.assertFalse(
            can_review_document(self.matter, 999, ["clinic_supervisor"])
        )
        self.assertFalse(can_review_document(self.matter, 101, ["clinic_student"]))

    def test_closed_matters_are_read_only(self) -> None:
        close_matter(self.matter, 202, now=NOW)
        self.assertTrue(can_view_matter(self.matter, 101, ["clinic_student"]))
        self.assertFalse(can_edit_facts(self.matter, 101, ["clinic_student"]))
        self.assertFalse(
            can_review_document(self.matter, 202, ["clinic_supervisor"])
        )

    def test_closed_matter_rejects_team_mutations(self) -> None:
        assign_team_member(self.matter, 202, "supervisor", 101, now=NOW)
        close_matter(
            self.matter,
            202,
            reason="administrative",
            now=NOW,
        )
        self.assertFalse(can_manage_team(self.matter, 101, ["clinic_student"]))
        self.assertFalse(can_manage_team(self.matter, 202, ["clinic_supervisor"]))
        self.assertFalse(can_manage_team(self.matter, 1, ["admin"]))

    def test_document_assignment_requires_an_active_student_worker(self) -> None:
        assign_document(self.matter, "joint_petition", 303, 101, now=NOW)
        self.assertEqual(
            self.matter["documents"]["joint_petition"]["assigned_user_id"], 303
        )
        with self.assertRaises(ClinicWorkspaceError):
            assign_document(self.matter, "joint_petition", 202, 101, now=NOW)

    def test_deactivation_removes_document_assignments(self) -> None:
        assign_document(self.matter, "joint_petition", 303, 101, now=NOW)
        deactivate_team_member(self.matter, 303, 101, now=NOW)
        self.assertIsNone(
            self.matter["documents"]["joint_petition"]["assigned_user_id"]
        )
        self.assertFalse(can_view_matter(self.matter, 303, ["clinic_student"]))

    def test_owner_role_cannot_be_changed_by_team_assignment(self) -> None:
        with self.assertRaises(ClinicWorkspaceError):
            assign_team_member(self.matter, 101, "collaborator", 202, now=NOW)

    def test_owner_can_be_reassigned_to_an_active_collaborator(self) -> None:
        reassign_matter_owner(self.matter, 303, 202, now=NOW)
        self.assertEqual(self.matter["owner_user_id"], 303)
        self.assertEqual(
            next(
                member["matter_role"]
                for member in self.matter["team_members"]
                if member["user_id"] == 101
            ),
            "collaborator",
        )


class DashboardTests(unittest.TestCase):
    def test_dashboard_filters_membership_before_pagination(self) -> None:
        summaries = []
        for index in range(40):
            matter = new_matter(
                101 if index % 2 == 0 else 202,
                f"MAT-{index:04d}",
                matter_id=f"matter-{index}",
                now=NOW,
            )
            summaries.append(safe_matter_summary(matter))
        visible = filter_visible_summaries(
            summaries, 101, ["clinic_student"], limit=10
        )
        self.assertEqual(len(visible), 10)
        self.assertTrue(all(101 in item["team_user_ids"] for item in visible))

    def test_admin_can_filter_all_safe_summaries(self) -> None:
        summaries = [
            safe_matter_summary(new_matter(101, "MAT-A", matter_id="a", now=NOW)),
            safe_matter_summary(new_matter(202, "MAT-B", matter_id="b", now=NOW)),
        ]
        visible = filter_visible_summaries(
            summaries, 999, ["clinic_admin"], limit=25
        )
        self.assertEqual({item["matter_id"] for item in visible}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
