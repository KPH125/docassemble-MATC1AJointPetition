"""Docassemble runtime adapter for clinic matter persistence and listing."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from docassemble.AssemblyLine.sessions import (
    find_matching_sessions,
    update_current_session_metadata,
)
from docassemble.base.util import (
    current_context,
    pdf_concatenate,
    user_info,
    user_privileges,
)

from .clinic_workspace import (
    SAFE_METADATA_KEYS,
    add_artifact,
    filter_visible_summaries,
    safe_matter_summary,
)


CLINIC_MATTER_FILENAME = (
    "docassemble.MATC1ADivorceJointPetition:"
    "data/questions/main_student_packet.yml"
)


def _concrete_pdf_sources(source_file: Any) -> List[Any]:
    """Resolve AssemblyLine documents into concrete files for freezing."""

    if isinstance(source_file, (list, tuple)):
        concrete: List[Any] = []
        for item in source_file:
            concrete.extend(_concrete_pdf_sources(item))
        return concrete
    as_pdf = getattr(source_file, "as_pdf", None)
    if callable(as_pdf):
        return [as_pdf()]
    return [source_file]


def durable_container_reference(container: Any, key: str) -> str:
    """Return a session-stable expression for an item stored in a DA container."""

    container_name = getattr(container, "instanceName", None)
    if container_name:
        return f"{container_name}[{key!r}]"
    return container[key].instanceName


def persist_current_matter_summary(matter: Mapping[str, Any]) -> Dict[str, Any]:
    """Write the safe dashboard projection for the current matter session."""

    summary = safe_matter_summary(matter)
    update_current_session_metadata(summary)
    return summary


def snapshot_generated_artifact(
    matter: Dict[str, Any],
    document_id: str,
    source_file: Any,
    generated_files: Any,
    actor_user_id: int,
    *,
    generation_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Freeze generated output as a distinct file before recording its version."""

    item = matter["documents"][document_id]
    if generation_token:
        existing = next(
            (
                artifact
                for artifact in item["artifacts"]
                if artifact.get("purpose") == "generated_draft"
                and artifact.get("details", {}).get("generation_token")
                == generation_token
            ),
            None,
        )
        if existing is not None:
            return existing
    version = len(item["artifacts"]) + 1
    revision = item["revision"] + 1
    storage_key = f"{document_id}_revision_{revision}_version_{version}"
    filename = f"{document_id}_revision_{revision}.pdf"
    generated_files[storage_key] = pdf_concatenate(
        *_concrete_pdf_sources(source_file),
        filename=filename,
    )
    file_reference = durable_container_reference(generated_files, storage_key)
    return add_artifact(
        matter,
        document_id,
        "generated_draft",
        actor_user_id,
        file_reference=file_reference,
        details={"generation_token": generation_token} if generation_token else None,
    )


def list_current_user_matter_summaries(
    *,
    status: Optional[str] = None,
    needs_review: bool = False,
    offset: int = 0,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """List only clinic matter summaries associated with the current user."""

    privileges = set(user_privileges())
    can_list_all = bool(privileges.intersection({"clinic_admin", "admin"}))
    records = find_matching_sessions(
        "",
        metadata_column_names=sorted(SAFE_METADATA_KEYS),
        filenames=[CLINIC_MATTER_FILENAME],
        user_id="all" if can_list_all else user_info().id,
        global_search_allowed_roles={"clinic_admin"},
        exclude_current_filename=False,
        limit=min(max(limit, 1), 100),
        offset=max(offset, 0),
    )
    summaries: List[Dict[str, Any]] = []
    for record in records:
        raw_data = record.get("data") or {}
        if raw_data.get("clinic_workspace"):
            summary = dict(raw_data)
            summary["session"] = record.get("key")
            summary["filename"] = record.get("filename") or CLINIC_MATTER_FILENAME
            # Session coordinates are used only after the safe projection has
            # passed policy filtering. They are not persisted as metadata.
            summaries.append(summary)

    safe_only = [
        {key: value for key, value in summary.items() if key not in {"session", "filename"}}
        for summary in summaries
    ]
    visible = filter_visible_summaries(
        safe_only,
        user_info().id,
        privileges,
        status=status,
        needs_review=needs_review,
        offset=0,
        limit=limit,
    )
    by_matter_id = {summary["matter_id"]: summary for summary in summaries}
    for summary in visible:
        coordinates = by_matter_id.get(summary["matter_id"], {})
        summary["session"] = coordinates.get("session")
        summary["filename"] = coordinates.get("filename")
    return visible


def current_session_coordinates() -> Dict[str, str]:
    context = current_context()
    return {"filename": context.filename, "session": context.session}
