from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import Mock


def load_repository_module():
    sessions_module = types.ModuleType("docassemble.AssemblyLine.sessions")
    sessions_module.find_matching_sessions = Mock(return_value=[])
    sessions_module.update_current_session_metadata = Mock()

    util_module = types.ModuleType("docassemble.base.util")
    util_module.current_context = Mock(
        return_value=types.SimpleNamespace(filename="matter.yml", session="session-1")
    )
    util_module.pdf_concatenate = Mock()
    util_module.user_info = Mock(return_value=types.SimpleNamespace(id=101))
    util_module.user_privileges = Mock(return_value=["clinic_student"])

    assembly_line_module = types.ModuleType("docassemble.AssemblyLine")
    base_module = types.ModuleType("docassemble.base")
    sys.modules["docassemble.AssemblyLine"] = assembly_line_module
    sys.modules["docassemble.AssemblyLine.sessions"] = sessions_module
    sys.modules["docassemble.base"] = base_module
    sys.modules["docassemble.base.util"] = util_module
    sys.modules.pop(
        "docassemble.MATC1ADivorceJointPetition.clinic_repository", None
    )
    return importlib.import_module(
        "docassemble.MATC1ADivorceJointPetition.clinic_repository"
    )


class RepositoryScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = load_repository_module()

    def test_student_query_uses_current_user_scope(self) -> None:
        self.repository.list_current_user_matter_summaries()
        kwargs = self.repository.find_matching_sessions.call_args.kwargs
        self.assertEqual(kwargs["user_id"], 101)
        self.assertEqual(kwargs["global_search_allowed_roles"], {"clinic_admin"})

    def test_clinic_admin_query_uses_explicit_global_scope(self) -> None:
        self.repository.user_privileges.return_value = ["clinic_admin"]
        self.repository.list_current_user_matter_summaries()
        kwargs = self.repository.find_matching_sessions.call_args.kwargs
        self.assertEqual(kwargs["user_id"], "all")

    def test_generated_snapshot_records_a_distinct_file_reference(self) -> None:
        from docassemble.MATC1ADivorceJointPetition.clinic_workspace import new_matter

        matter = new_matter(101, "MAT-0042")
        generated_files = {}
        frozen_file = types.SimpleNamespace(instanceName="clinic_generated_files[key]")
        self.repository.pdf_concatenate.return_value = frozen_file

        artifact = self.repository.snapshot_generated_artifact(
            matter,
            "joint_petition",
            types.SimpleNamespace(instanceName="live_attachment"),
            generated_files,
            101,
        )

        self.assertEqual(artifact["file_reference"], "clinic_generated_files[key]")
        self.assertEqual(artifact["revision"], 1)
        self.assertEqual(len(generated_files), 1)

    def test_generated_snapshot_resolves_assemblyline_documents_to_pdf(self) -> None:
        from docassemble.MATC1ADivorceJointPetition.clinic_workspace import new_matter

        matter = new_matter(101, "MAT-0043")
        generated_files = {}
        concrete_pdf = types.SimpleNamespace(instanceName="motion.pdf")
        document = types.SimpleNamespace(as_pdf=Mock(return_value=concrete_pdf))
        frozen_file = types.SimpleNamespace(instanceName="clinic_generated_files[key]")
        self.repository.pdf_concatenate.return_value = frozen_file

        self.repository.snapshot_generated_artifact(
            matter,
            "motion_to_amend",
            document,
            generated_files,
            101,
        )

        document.as_pdf.assert_called_once_with()
        self.repository.pdf_concatenate.assert_called_once_with(
            concrete_pdf,
            filename="motion_to_amend_revision_1.pdf",
        )

    def test_generated_snapshot_flattens_multi_document_packets(self) -> None:
        first_pdf = object()
        second_pdf = object()
        first = types.SimpleNamespace(as_pdf=Mock(return_value=first_pdf))
        second = types.SimpleNamespace(as_pdf=Mock(return_value=second_pdf))

        self.assertEqual(
            self.repository._concrete_pdf_sources([first, [second]]),
            [first_pdf, second_pdf],
        )

    def test_generated_snapshot_uses_a_durable_container_reference(self) -> None:
        from docassemble.MATC1ADivorceJointPetition.clinic_workspace import new_matter

        class NamedDict(dict):
            instanceName = "clinic_generated_files"

        matter = new_matter(101, "MAT-0044")
        generated_files = NamedDict()
        frozen_file = types.SimpleNamespace(instanceName="temporaryRandomName")
        self.repository.pdf_concatenate.return_value = frozen_file

        artifact = self.repository.snapshot_generated_artifact(
            matter,
            "joint_petition",
            object(),
            generated_files,
            101,
        )

        self.assertEqual(
            artifact["file_reference"],
            "clinic_generated_files['joint_petition_revision_1_version_1']",
        )

    def test_generated_snapshot_is_idempotent_within_one_generation_run(self) -> None:
        from docassemble.MATC1ADivorceJointPetition.clinic_workspace import new_matter

        matter = new_matter(101, "MAT-0045")
        generated_files = {}
        frozen_file = types.SimpleNamespace(instanceName="clinic_generated_files[key]")
        self.repository.pdf_concatenate.return_value = frozen_file

        first = self.repository.snapshot_generated_artifact(
            matter,
            "joint_petition",
            object(),
            generated_files,
            101,
            generation_token="generation-1",
        )
        second = self.repository.snapshot_generated_artifact(
            matter,
            "joint_petition",
            object(),
            generated_files,
            101,
            generation_token="generation-1",
        )

        self.assertIs(first, second)
        self.assertEqual(len(matter["documents"]["joint_petition"]["artifacts"]), 1)
        self.repository.pdf_concatenate.assert_called_once()

    def test_received_file_reference_uses_its_durable_container_path(self) -> None:
        class NamedDict(dict):
            instanceName = "clinic_received_files"

        received_files = NamedDict(received_7=types.SimpleNamespace(instanceName="random"))

        self.assertEqual(
            self.repository.durable_container_reference(received_files, "received_7"),
            "clinic_received_files['received_7']",
        )


if __name__ == "__main__":
    unittest.main()
