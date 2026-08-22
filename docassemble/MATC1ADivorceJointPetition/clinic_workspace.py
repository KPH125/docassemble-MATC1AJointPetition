"""Domain rules for the clinic divorce matter workspace.

This module intentionally has no Docassemble imports. Interview YAML and the
runtime repository adapter call these functions, while unit and performance
tests can exercise the same rules in ordinary Python.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import re
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set
from uuid import uuid4


SCHEMA_VERSION = 2

CLINIC_PRIVILEGES = frozenset(
    {"clinic_student", "clinic_supervisor", "clinic_admin"}
)
STAFF_MATTER_ROLES = frozenset(
    {"owner", "collaborator", "supervisor", "viewer"}
)
CASE_RELATIONSHIPS = frozenset(
    {"represented_client", "assisted_party", "other_party", "signer"}
)

PLAN_STATUSES = frozenset(
    {"not_selected", "prepare_now", "court_use_bundle", "records_bundle", "later"}
)
BUNDLE_TYPES = frozenset({"court_use", "records"})
SOURCE_STATUSES = frozenset(
    {"not_received", "confirmed_existing", "uploaded_reference", "generated", "external_working_draft"}
)
REVIEW_STATUSES = frozenset(
    {"not_started", "in_progress", "ready_for_review", "changes_requested", "approved"}
)
EXECUTION_STATUSES = frozenset(
    {"draft", "ready_for_signature", "signed", "notarized", "needs_revision", "filed"}
)
DELIVERY_STATUSES = frozenset(
    {"not_selected", "court_use_bundle", "records_bundle", "delivered", "filed"}
)
ARTIFACT_PURPOSES = frozenset(
    {
        "existing_reference",
        "external_working_draft",
        "client_annotated_reference",
        "generated_draft",
        "signed_copy",
        "notarized_copy",
        "filed_copy",
        "court_returned_copy",
    }
)
ARTIFACT_DISPOSITIONS = frozenset(
    {"reference_only", "use_exact_file", "update_answers_and_regenerate"}
)
ARTIFACT_DETAIL_KEYS = frozenset(
    {"event_date", "filing_method", "court_outcome", "court_note", "generation_token"}
)
CLOSURE_REASONS = frozenset(
    {"completed", "withdrawn", "transferred", "administrative"}
)

REVIEW_TRANSITIONS = {
    "not_started": {"in_progress"},
    "in_progress": {"ready_for_review", "not_started"},
    "ready_for_review": {"changes_requested", "approved", "in_progress"},
    "changes_requested": {"in_progress", "ready_for_review"},
    "approved": {"in_progress", "changes_requested"},
}

EXECUTION_TRANSITIONS = {
    "draft": {"ready_for_signature", "needs_revision"},
    "ready_for_signature": {"signed", "needs_revision", "draft"},
    "signed": {"notarized", "filed", "needs_revision"},
    "notarized": {"filed", "needs_revision"},
    "needs_revision": {"draft", "ready_for_signature"},
    "filed": {"needs_revision"},
}


DOCUMENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "motion_to_amend": {
        "title": "Motion to convert a 1B divorce to a joint 1A divorce",
        "family": "case_start",
        "requires": [],
        "workflow_event": "clinic_work_motion_to_amend",
        "review_event": "review_motion_to_amend",
        "review_sections": ["case", "parties", "representation", "signatures"],
    },
    "joint_petition": {
        "title": "Joint petition for divorce",
        "family": "case_start",
        "requires": [],
        "workflow_event": "clinic_work_joint_petition",
        "review_event": "review_divorcejointpetition",
        "review_sections": ["parties", "relationship", "children", "court", "requests"],
    },
    "irretrievable_breakdown_affidavit": {
        "title": "Affidavit of irretrievable breakdown",
        "family": "case_start",
        "requires": ["joint_petition"],
        "workflow_event": "clinic_work_joint_petition",
        "review_event": "review_divorcejointpetition",
        "review_sections": ["parties", "relationship", "signatures"],
    },
    "r408": {
        "title": "Report of Absolute Divorce or Annulment (R408)",
        "family": "case_start",
        "requires": ["joint_petition"],
        "workflow_event": "clinic_work_r408",
        "review_event": None,
        "review_sections": ["parties", "relationship", "children", "court"],
    },
    "late_marriage_certificate_motion": {
        "title": "Motion to file marriage certificate late",
        "family": "case_start",
        "requires": ["joint_petition"],
        "workflow_event": "clinic_work_late_marriage_certificate_motion",
        "review_event": "review_jointmotiontofilemarriagecertificatelate",
        "review_sections": ["parties", "marriage_certificate", "court"],
    },
    "care_or_custody_affidavit": {
        "title": "Affidavit disclosing care or custody proceedings",
        "family": "children",
        "requires": ["joint_petition"],
        "workflow_event": "clinic_work_care_or_custody_affidavit",
        "review_event": None,
        "review_sections": ["children", "custody_cases", "addresses"],
    },
    "child_support_guidelines": {
        "title": "Child Support Guidelines Worksheet",
        "family": "children",
        "requires": ["joint_petition"],
        "workflow_event": "clinic_work_child_support_guidelines",
        "review_event": "review_ma_child_support_guidelines_worksheet",
        "review_sections": ["parents", "children", "income", "deductions", "childcare"],
    },
    "findings_and_determinations": {
        "title": "Findings and Determinations",
        "family": "children",
        "requires": ["child_support_guidelines"],
        "workflow_event": "clinic_work_findings_and_determinations",
        "review_event": "review_cjd_305",
        "review_sections": ["income", "coverage", "education", "deviation"],
    },
    "financial_statement_party_a": {
        "title": "Financial statement for Party A",
        "family": "financial",
        "requires": [],
        "workflow_event": "clinic_work_financial_statements",
        "review_event": "review_fs",
        "review_sections": ["party_a_income", "party_a_expenses", "party_a_assets", "party_a_liabilities"],
    },
    "financial_statement_party_b": {
        "title": "Financial statement for Party B",
        "family": "financial",
        "requires": [],
        "workflow_event": "clinic_work_financial_statements",
        "review_event": "review_fs",
        "review_sections": ["party_b_income", "party_b_expenses", "party_b_assets", "party_b_liabilities"],
    },
    "separation_agreement": {
        "title": "Separation agreement",
        "family": "agreement",
        "requires": ["joint_petition"],
        "workflow_event": "clinic_work_separation_agreement",
        "review_event": "review_a_divorce_agreement",
        "review_sections": ["parties", "children", "support", "property", "debts", "signatures"],
    },
    "affidavit_of_indigency": {
        "title": "Affidavit of indigency",
        "family": "fees",
        "requires": [],
        "workflow_event": "clinic_work_affidavit_of_indigency",
        "review_event": "review_affidavit_of_indigency",
        "review_sections": ["applicant", "income", "benefits", "expenses", "fees"],
    },
    "temporary_orders_packet": {
        "title": "Temporary orders packet",
        "family": "temporary_orders",
        "requires": [],
        "workflow_event": "clinic_work_temporary_orders",
        "review_event": "temporary_orders_review_answers",
        "review_sections": ["case", "parties", "requested_orders", "facts", "service"],
    },
}


# Leaf answers exposed by the clinic-owned review screen. Revisit events are
# intentionally omitted: the clinic screen must ask concrete variables that
# return to the same document workspace instead of entering a child interview's
# standalone navigation.
CLINIC_DOCUMENT_REVIEW_VARIABLES: Dict[str, tuple[str, ...]] = {
    "motion_to_amend": (
        "trial_court",
        "docket_number",
        "users[plaintiff_index].name.first",
        "users[defendant_index].name.first",
        "marriage_breakdown_date",
        "breakdown_location",
        "action_commenced_date",
        "users[plaintiff_index].has_attorney",
        "attorneys[plaintiff_index].name.first",
        "attorneys[plaintiff_index].address.address",
        "attorneys[plaintiff_index].phone_number",
        "users[plaintiff_index].address.address",
        "users[plaintiff_index].phone_number",
        "users[defendant_index].has_attorney",
        "attorneys[defendant_index].name.first",
        "attorneys[defendant_index].address.address",
        "attorneys[defendant_index].phone_number",
        "users[defendant_index].address.address",
        "users[defendant_index].phone_number",
        "signature_date",
    ),
    "joint_petition": (
        "trial_court",
        "docket_number",
        "marriage_date",
        "last_living_together_date",
        "previous_action_detail",
        "marriage_breakdown_date",
        "request_merge_agreement",
        "request_survive_agreement",
        "users1_request_name_change",
        "users1_former_name_last",
        "users2_request_name_change",
        "users2_former_name_last",
        "additional_request",
        "additonal_request_detail",
        "signature_date",
        "users[0].signature",
        "attorneys[0].signature",
        "users[1].signature",
        "attorneys[1].signature",
        "users[0].has_attorney",
        "attorneys[0].name.first",
        "attorneys[1].name.first",
    ),
    "irretrievable_breakdown_affidavit": (
        "marriage_breakdown_date",
        "signature_date",
        "users[0].signature",
        "attorneys[0].signature",
        "users[1].signature",
        "attorneys[1].signature",
    ),
    "r408": (
        "users[0].birthdate",
        "users[1].birthdate",
        "users1_number_of_custodial_children",
        "users2_number_of_custodial_children",
        "users1_gender",
        "users2_gender",
        "users1_ssn_last_four",
        "users2_ssn_last_four",
        "users1_marriage_number",
        "users2_marriage_number",
        "users1_name_last_at_birth",
        "users2_name_last_at_birth",
        "r408_addendum",
    ),
    "late_marriage_certificate_motion": (
        "marriage_state",
        "marriage_proof_delay_action_plan",
        "trial_court",
        "marriage_city",
        "marriage_date",
        "marriage_country",
        "signature_date",
        "marriage_proof_delay_reason",
        "docket_number",
        "international_marriage",
    ),
    "care_or_custody_affidavit": (
        "children[0].name.first",
        "children[0].address.address",
        "children[0].address.start_date",
        "children[0].lives_with",
        "children[0].relationship",
        "custody_case_participation",
        "confidential_address_reasons",
        "needs_attorney_signature",
        "signing_attorney.address.address",
        "signature_date",
    ),
    "child_support_guidelines": (
        "case_name",
        "parenting_box",
        "users[0].name.first",
        "users[0].gross_weekly_income_amount",
        "social_security_dependency_benefits_yes",
        "users[0].other_support_paid_amount",
        "child1_care_paid_by_user_amount",
    ),
    "findings_and_determinations": (
        "case_name",
        "docket_number",
        "trial_court_division",
        "payor_name",
        "recipient_name",
        "combined_income_over_400k",
        "payor_income_imputed",
        "recipient_income_imputed",
        "payor_unemployed_underemployed",
        "payor_earning_less_than_reasonable",
        "recipient_unemployed_underemployed",
        "recipient_earning_less_than_reasonable",
        "child_1_18_23_high_school",
        "child_2_18_23_high_school",
        "payor_postsecondary_above_50pct",
        "recipient_postsecondary_above_50pct",
        "payor_healthcare_extra_cost_reduces",
        "recipient_healthcare_extra_cost_reduces",
        "payor_healthcare_not_best_interest",
        "recipient_healthcare_not_best_interest",
        "payor_dental_extra_cost_reduces",
        "recipient_dental_extra_cost_reduces",
        "guidelines_support_amount",
        "guidelines_frequency",
        "deviation_parties_agree",
    ),
    "financial_statement_party_a": (
        "trial_court",
        "docket_number",
        "users[i].name.first",
        "users[i].birthdate",
        "users[i].phone_number",
        "users[i].address.address",
        "users[i].financial_cadence_default",
        "users[i].income_list.revisit",
        "users[i].income_explanation_note",
        "users[i].expense_list.revisit",
        "users[i].long_expense_list.revisit",
        "users[i].motor_vehicles.revisit",
        "users[i].pensions.revisit",
        "users[i].other_assets.revisit",
        "users[i].liabilities.revisit",
        "users[i].schedule_a_expenses.revisit",
        "users[i].schedule_b_expenses.revisit",
        "users[i].has_self_employment_income",
        "users[i].has_rental_income",
    ),
    "financial_statement_party_b": (
        "trial_court",
        "docket_number",
        "users[i].name.first",
        "users[i].birthdate",
        "users[i].phone_number",
        "users[i].address.address",
        "users[i].financial_cadence_default",
        "users[i].income_list.revisit",
        "users[i].income_explanation_note",
        "users[i].expense_list.revisit",
        "users[i].long_expense_list.revisit",
        "users[i].motor_vehicles.revisit",
        "users[i].pensions.revisit",
        "users[i].other_assets.revisit",
        "users[i].liabilities.revisit",
        "users[i].schedule_a_expenses.revisit",
        "users[i].schedule_b_expenses.revisit",
        "users[i].has_self_employment_income",
        "users[i].has_rental_income",
    ),
    "separation_agreement": (
        "has_children",
        "custody_type_choice",
        "parenting_time_assigned",
        "child_support_payer",
        "child_support_guideline_amount",
        "child_support_deviation",
        "health_insurance_provided_for_children",
        "education_cost_based_on_ability",
        "child_tax_claim_single_party",
        "health_insurance_custom_terms_adult",
        "taxes_custom_terms",
        "alimony_waived_all",
        "no_real_estate",
        "personal_property_already_divided",
        "no_marital_debt",
        "no_retirement_benefits",
        "no_life_insurance",
        "provisions_that_merge",
        "trial_court",
        "signature_date",
        "docket_number",
    ),
    "affidavit_of_indigency": (
        "trial_court",
        "case_name",
        "docket_numbers[0]",
        "user_grade_school_completed",
        "user_training",
        "has_disabilities",
        "user_owns_home",
        "user_owns_car",
        "user_owns_property",
        "user_debts",
        "miscellaneous_facts",
        "signature_date",
    ),
    "temporary_orders_packet": (
        "trial_court",
        "docket_number",
        "temporary_orders_caption_plaintiff_petitioner_name",
        "temporary_orders_caption_defendant_respondent_name",
        "temporary_orders_moving_party_name",
        "temporary_orders_requested_relief",
        "temporary_orders_is_emergency",
        "temporary_orders_affidavit_facts",
        "temporary_orders_needs_service",
        "temporary_orders_service_method",
        "temporary_orders_signature_date",
    ),
}


CLINIC_REVIEW_LABEL_OVERRIDES = {
    "trial_court": "Court",
    "trial_court_division": "Court division",
    "docket_number": "Docket number",
    "docket_numbers[0]": "Docket number",
    "users[0].name.first": "Party A name",
    "users[1].name.first": "Party B name",
    "users[plaintiff_index].name.first": "Plaintiff name",
    "users[defendant_index].name.first": "Defendant name",
    "users[i].name.first": "Selected party name",
    "users[i].birthdate": "Selected party birth date",
    "users[i].phone_number": "Selected party phone number",
    "users[i].address.address": "Selected party address",
    "users[0].signature": "Party A signature",
    "users[1].signature": "Party B signature",
    "attorneys[0].signature": "Party A attorney signature",
    "attorneys[1].signature": "Party B attorney signature",
    "children[0].name.first": "First child's name",
    "children[0].address.address": "First child's current address",
    "children[0].address.start_date": "First child's current address start date",
    "children[0].lives_with": "Who the first child lives with",
    "children[0].relationship": "First child's relationship to household members",
    "custody_case_participation": "Other care or custody cases",
    "confidential_address_reasons": "Address confidentiality",
    "needs_attorney_signature": "Attorney signature requirement",
    "signing_attorney.address.address": "Signing attorney address",
    "users[i].income_list.revisit": "Income entries",
    "users[i].expense_list.revisit": "Short-form expense entries",
    "users[i].long_expense_list.revisit": "Long-form expense entries",
    "users[i].motor_vehicles.revisit": "Motor vehicles",
    "users[i].pensions.revisit": "Pensions and retirement assets",
    "users[i].other_assets.revisit": "Other assets",
    "users[i].liabilities.revisit": "Liabilities",
    "users[i].schedule_a_expenses.revisit": "Self-employment schedule",
    "users[i].schedule_b_expenses.revisit": "Rental-property schedule",
}


def clinic_document_review_entries(document_id: str) -> List[Dict[str, str]]:
    """Return human-readable, concrete answer targets for a clinic document."""

    entries = []
    party_index = {
        "financial_statement_party_a": 0,
        "financial_statement_party_b": 1,
    }.get(document_id)
    for variable in CLINIC_DOCUMENT_REVIEW_VARIABLES.get(document_id, ()):
        label = CLINIC_REVIEW_LABEL_OVERRIDES.get(variable)
        if not label:
            leaf = variable.split(".")[-1]
            leaf = re.sub(r"\[[^]]+\]", "", leaf)
            label = leaf.replace("_", " ").strip().capitalize()
        concrete_variable = (
            variable.replace("[i]", f"[{party_index}]")
            if party_index is not None
            else variable
        )
        entries.append({"variable": concrete_variable, "label": label})
    return entries

CHANGE_IMPACT_MAP: Dict[str, Set[str]] = {
    "motion_to_amend": {"motion_to_amend", "joint_petition"},
    "irretrievable_breakdown_affidavit": {
        "irretrievable_breakdown_affidavit",
        "joint_petition",
    },
    "r408": {"r408", "joint_petition"},
    "late_marriage_certificate_motion": {
        "late_marriage_certificate_motion",
        "joint_petition",
    },
    "care_or_custody_affidavit": {
        "care_or_custody_affidavit",
        "joint_petition",
        "separation_agreement",
    },
    "child_support_guidelines": {
        "child_support_guidelines",
        "findings_and_determinations",
        "separation_agreement",
    },
    "findings_and_determinations": {"findings_and_determinations"},
    "financial_statement_party_a": {
        "financial_statement_party_a",
        "child_support_guidelines",
        "findings_and_determinations",
        "separation_agreement",
    },
    "financial_statement_party_b": {
        "financial_statement_party_b",
        "child_support_guidelines",
        "findings_and_determinations",
        "separation_agreement",
    },
    "separation_agreement": {"separation_agreement", "joint_petition"},
    "affidavit_of_indigency": {"affidavit_of_indigency"},
    "temporary_orders_packet": {"temporary_orders_packet"},
}

SAFE_METADATA_KEYS = frozenset(
    {
        "clinic_workspace",
        "matter_id",
        "safe_label",
        "owner_user_id",
        "team_user_ids",
        "supervisor_user_ids",
        "case_posture",
        "overall_status",
        "next_action",
        "blocked_count",
        "due_date",
        "updated_at",
        "schema_version",
        "progress",
        "title",
        "auto_title",
        "description",
    }
)


class ClinicWorkspaceError(ValueError):
    """Raised when a requested clinic workspace operation violates a domain rule."""


def utc_now_iso(now: Optional[datetime] = None) -> str:
    """Return a stable UTC timestamp for persisted activity and metadata."""

    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_choice(value: str, choices: Set[str] | frozenset, label: str) -> str:
    if value not in choices:
        raise ClinicWorkspaceError(f"Unsupported {label}: {value}")
    return value


def normalize_safe_label(value: str) -> str:
    """Normalize the non-confidential label used in dashboard metadata."""

    label = " ".join(str(value or "").split()).strip()
    if not label:
        raise ClinicWorkspaceError("A clinic-safe matter label is required")
    if len(label) > 80:
        raise ClinicWorkspaceError("The clinic-safe matter label cannot exceed 80 characters")
    if any(character in label for character in '<>&"\'`/\\'):
        raise ClinicWorkspaceError(
            "The clinic-safe matter label cannot contain markup or path characters"
        )
    return label


def display_text(value: Any) -> str:
    """Escape stored text before inserting it into workspace-authored HTML."""

    return escape(str(value or ""), quote=True)


def new_document_work_item(document_id: str) -> Dict[str, Any]:
    if document_id not in DOCUMENT_REGISTRY:
        raise ClinicWorkspaceError(f"Unsupported document: {document_id}")
    return {
        "document_id": document_id,
        "plan_status": "not_selected",
        "source_status": "not_received",
        "review_status": "not_started",
        "execution_status": "draft",
        "delivery_status": "not_selected",
        "assigned_user_id": None,
        "bundle_destinations": [],
        "dependency_blockers": [],
        "artifacts": [],
        "review_history": [],
        "revision": 0,
        "updated_at": None,
    }


def new_matter(
    owner_user_id: int,
    safe_label: str,
    *,
    matter_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create a complete, versioned clinic matter dictionary."""

    if not isinstance(owner_user_id, int) or owner_user_id <= 0:
        raise ClinicWorkspaceError("The owner must have a positive integer user ID")
    timestamp = utc_now_iso(now)
    resolved_id = matter_id or str(uuid4())
    documents = {
        document_id: new_document_work_item(document_id)
        for document_id in DOCUMENT_REGISTRY
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "matter_id": resolved_id,
        "safe_label": normalize_safe_label(safe_label),
        "case_posture": "unselected",
        "overall_status": "active",
        "next_action": "complete_matter_setup",
        "due_date": None,
        "owner_user_id": owner_user_id,
        "team_members": [
            {
                "user_id": owner_user_id,
                "matter_role": "owner",
                "active": True,
                "assigned_at": timestamp,
                "assigned_by_user_id": owner_user_id,
            }
        ],
        "party_relationships": [],
        "filing_plan": {"task": "unselected", "updated_at": timestamp},
        "documents": documents,
        "reference_files": [],
        "internal_notes": [],
        "activity": [
            {
                "event": "matter_created",
                "actor_user_id": owner_user_id,
                "at": timestamp,
                "document_id": None,
            }
        ],
        "created_at": timestamp,
        "updated_at": timestamp,
        "closed_at": None,
        "closed_by_user_id": None,
        "closure_reason": None,
    }


def normalize_matter(matter: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a current-schema copy and add safe defaults for older sessions."""

    result = deepcopy(dict(matter))
    result["schema_version"] = SCHEMA_VERSION
    result.setdefault("overall_status", "active")
    result.setdefault("next_action", "review_matter")
    result.setdefault("due_date", None)
    result.setdefault("team_members", [])
    result.setdefault("party_relationships", [])
    result.setdefault("filing_plan", {"task": "unselected", "updated_at": None})
    result.setdefault("documents", {})
    result.setdefault("reference_files", [])
    result.setdefault("internal_notes", [])
    result.setdefault("activity", [])
    result.setdefault("closed_at", None)
    result.setdefault("closed_by_user_id", None)
    result.setdefault("closure_reason", None)
    for document_id in DOCUMENT_REGISTRY:
        if document_id not in result["documents"]:
            result["documents"][document_id] = new_document_work_item(document_id)
        else:
            default_item = new_document_work_item(document_id)
            default_item.update(result["documents"][document_id])
            result["documents"][document_id] = default_item
        item = result["documents"][document_id]
        if not item.get("bundle_destinations") and item["plan_status"] in {
            "court_use_bundle",
            "records_bundle",
        }:
            item["bundle_destinations"] = [
                "court_use" if item["plan_status"] == "court_use_bundle" else "records"
            ]
            item["plan_status"] = "prepare_now"
        for artifact in item["artifacts"]:
            artifact.setdefault("details", {})
            artifact.setdefault("superseded_at", None)
            artifact.setdefault("superseded_by_artifact_id", None)
            artifact.setdefault("intake_disposition", None)
            if "eligible_bundle_types" not in artifact:
                artifact["eligible_bundle_types"] = (
                    ["records"]
                    if artifact.get("eligible_for_bundle")
                    and artifact.get("purpose") in {"filed_copy", "court_returned_copy"}
                    else ["court_use", "records"]
                    if artifact.get("eligible_for_bundle")
                    else []
                )
    return result


def matter_workflow_progress(matter: Mapping[str, Any]) -> Dict[str, int]:
    """Summarize visible workflow progress without implying court completion.

    The score measures only work represented inside this workspace: matter setup,
    a current artifact, supervisor approval, and a verified execution artifact.
    Closure is the only state that reports 100 percent.  The component counts are
    returned with the score so the interface can explain the number precisely.
    """

    selected = [
        item
        for item in matter.get("documents", {}).values()
        if item.get("plan_status") != "not_selected"
    ]
    total = len(selected)
    if matter.get("overall_status") == "closed":
        return {
            "percent": 100,
            "selected": total,
            "with_current_file": total,
            "approved": total,
            "executed": total,
        }
    if not selected:
        return {
            "percent": 10,
            "selected": 0,
            "with_current_file": 0,
            "approved": 0,
            "executed": 0,
        }

    with_current_file = sum(
        any(not artifact.get("superseded_at") for artifact in item.get("artifacts", []))
        for item in selected
    )
    approved = sum(item.get("review_status") == "approved" for item in selected)
    executed = sum(
        item.get("execution_status") in {"signed", "notarized", "filed"}
        for item in selected
    )
    percent = round(
        10
        + 60 * with_current_file / total
        + 20 * approved / total
        + 10 * executed / total
    )
    return {
        "percent": min(percent, 99),
        "selected": total,
        "with_current_file": with_current_file,
        "approved": approved,
        "executed": executed,
    }


def record_activity(
    matter: MutableMapping[str, Any],
    event: str,
    actor_user_id: int,
    *,
    document_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Record a fixed, non-confidential event name in the matter audit trail."""

    if not event or any(character.isspace() for character in event):
        raise ClinicWorkspaceError("Activity event names must be non-empty identifiers")
    timestamp = utc_now_iso(now)
    matter.setdefault("activity", []).append(
        {
            "event": event,
            "actor_user_id": actor_user_id,
            "at": timestamp,
            "document_id": document_id,
        }
    )
    matter["updated_at"] = timestamp


def assign_team_member(
    matter: MutableMapping[str, Any],
    user_id: int,
    matter_role: str,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Add or reactivate a staff matter membership using a stable user ID."""

    _require_choice(matter_role, STAFF_MATTER_ROLES, "matter role")
    if not isinstance(user_id, int) or user_id <= 0:
        raise ClinicWorkspaceError("Team members must have positive integer user IDs")
    if user_id == matter.get("owner_user_id") and matter_role != "owner":
        raise ClinicWorkspaceError("Use an owner reassignment workflow to change the owner")
    if matter_role == "owner" and user_id != matter.get("owner_user_id"):
        raise ClinicWorkspaceError("A matter cannot have a second owner")
    timestamp = utc_now_iso(now)
    for member in matter.setdefault("team_members", []):
        if member.get("user_id") == user_id:
            member.update(
                {
                    "matter_role": matter_role,
                    "active": True,
                    "assigned_at": timestamp,
                    "assigned_by_user_id": actor_user_id,
                }
            )
            break
    else:
        matter["team_members"].append(
            {
                "user_id": user_id,
                "matter_role": matter_role,
                "active": True,
                "assigned_at": timestamp,
                "assigned_by_user_id": actor_user_id,
            }
        )
    record_activity(matter, "team_member_assigned", actor_user_id, now=now)


def assign_document(
    matter: MutableMapping[str, Any],
    document_id: str,
    user_id: Optional[int],
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Assign selected document work to an active student worker."""

    if document_id not in DOCUMENT_REGISTRY:
        raise ClinicWorkspaceError(f"Unsupported document: {document_id}")
    if user_id is not None:
        if not isinstance(user_id, int) or user_id <= 0:
            raise ClinicWorkspaceError("Document assignees must have positive integer user IDs")
        if active_matter_role(matter, user_id) not in {"owner", "collaborator"}:
            raise ClinicWorkspaceError("Document work can be assigned only to an active student worker")
    item = matter["documents"][document_id]
    item["assigned_user_id"] = user_id
    item["updated_at"] = utc_now_iso(now)
    record_activity(
        matter,
        "document_assignment_updated",
        actor_user_id,
        document_id=document_id,
        now=now,
    )


def deactivate_team_member(
    matter: MutableMapping[str, Any],
    user_id: int,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Remove active matter access without deleting historical identity."""

    if user_id == matter.get("owner_user_id"):
        raise ClinicWorkspaceError("Reassign the owner before deactivating that membership")
    for member in matter.get("team_members", []):
        if member.get("user_id") == user_id and member.get("active"):
            member["active"] = False
            for document in matter.get("documents", {}).values():
                if document.get("assigned_user_id") == user_id:
                    document["assigned_user_id"] = None
            record_activity(matter, "team_member_deactivated", actor_user_id, now=now)
            return
    raise ClinicWorkspaceError("The user does not have an active matter membership")


def reassign_matter_owner(
    matter: MutableMapping[str, Any],
    new_owner_user_id: int,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Transfer ownership to an active student collaborator."""

    old_owner_user_id = matter["owner_user_id"]
    if new_owner_user_id == old_owner_user_id:
        return
    if active_matter_role(matter, new_owner_user_id) != "collaborator":
        raise ClinicWorkspaceError(
            "The new owner must already be an active student collaborator"
        )
    for member in matter["team_members"]:
        if member.get("user_id") == old_owner_user_id and member.get("active"):
            member["matter_role"] = "collaborator"
        elif member.get("user_id") == new_owner_user_id and member.get("active"):
            member["matter_role"] = "owner"
    matter["owner_user_id"] = new_owner_user_id
    record_activity(matter, "matter_owner_reassigned", actor_user_id, now=now)


def active_matter_role(matter: Mapping[str, Any], user_id: int) -> Optional[str]:
    for member in matter.get("team_members", []):
        if member.get("user_id") == user_id and member.get("active"):
            return member.get("matter_role")
    return None


def has_clinic_privilege(privileges: Iterable[str]) -> bool:
    privilege_set = set(privileges)
    return "admin" in privilege_set or bool(
        privilege_set.intersection(CLINIC_PRIVILEGES)
    )


def can_view_matter(
    matter: Mapping[str, Any], user_id: int, privileges: Iterable[str]
) -> bool:
    privilege_set = set(privileges)
    if privilege_set.intersection({"clinic_admin", "admin"}):
        return True
    if not privilege_set.intersection(CLINIC_PRIVILEGES):
        return False
    return active_matter_role(matter, user_id) is not None


def can_edit_facts(
    matter: Mapping[str, Any], user_id: int, privileges: Iterable[str]
) -> bool:
    if matter.get("overall_status") == "closed":
        return False
    if set(privileges).intersection({"clinic_admin", "admin"}):
        return True
    return can_view_matter(matter, user_id, privileges) and active_matter_role(
        matter, user_id
    ) in {"owner", "collaborator"}


def can_review_document(
    matter: Mapping[str, Any], user_id: int, privileges: Iterable[str]
) -> bool:
    privilege_set = set(privileges)
    if matter.get("overall_status") == "closed":
        return False
    if privilege_set.intersection({"clinic_admin", "admin"}):
        return True
    return (
        "clinic_supervisor" in privilege_set
        and active_matter_role(matter, user_id) == "supervisor"
    )


def can_manage_team(
    matter: Mapping[str, Any], user_id: int, privileges: Iterable[str]
) -> bool:
    if matter.get("overall_status") == "closed":
        return False
    privilege_set = set(privileges)
    if privilege_set.intersection({"clinic_admin", "admin"}):
        return True
    role = active_matter_role(matter, user_id)
    return can_view_matter(matter, user_id, privilege_set) and (
        role == "owner"
        or (role == "supervisor" and "clinic_supervisor" in privilege_set)
    )


def can_close_matter(
    matter: Mapping[str, Any], user_id: int, privileges: Iterable[str]
) -> bool:
    if matter.get("overall_status") == "closed":
        return False
    privilege_set = set(privileges)
    if privilege_set.intersection({"clinic_admin", "admin"}):
        return True
    return (
        "clinic_supervisor" in privilege_set
        and active_matter_role(matter, user_id) == "supervisor"
    )


def can_add_internal_note(
    matter: Mapping[str, Any], user_id: int, privileges: Iterable[str]
) -> bool:
    if matter.get("overall_status") == "closed":
        return False
    if set(privileges).intersection({"clinic_admin", "admin"}):
        return True
    return can_view_matter(matter, user_id, privileges) and active_matter_role(
        matter, user_id
    ) in {"owner", "collaborator", "supervisor"}


def add_internal_note(
    matter: MutableMapping[str, Any],
    text: str,
    actor_user_id: int,
    *,
    document_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Add a confidential collaboration note without copying it to metadata."""

    cleaned_text = "\n".join(
        line.rstrip() for line in str(text or "").strip().splitlines()
    )
    if not cleaned_text:
        raise ClinicWorkspaceError("An internal note cannot be empty")
    if len(cleaned_text) > 2000:
        raise ClinicWorkspaceError("An internal note cannot exceed 2,000 characters")
    if document_id is not None and document_id not in DOCUMENT_REGISTRY:
        raise ClinicWorkspaceError(f"Unsupported document: {document_id}")
    note = {
        "note_id": str(uuid4()),
        "text": cleaned_text,
        "actor_user_id": actor_user_id,
        "document_id": document_id,
        "at": utc_now_iso(now),
    }
    matter.setdefault("internal_notes", []).append(note)
    record_activity(
        matter,
        "internal_note_added",
        actor_user_id,
        document_id=document_id,
        now=now,
    )
    return note


def set_case_relationship(
    matter: MutableMapping[str, Any],
    party_index: int,
    relationship: str,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    _require_choice(relationship, CASE_RELATIONSHIPS, "case relationship")
    if party_index not in (0, 1):
        raise ClinicWorkspaceError("Only Party A and Party B are supported")
    relationships = matter.setdefault("party_relationships", [])
    for item in relationships:
        if item.get("party_index") == party_index:
            item["relationship"] = relationship
            break
    else:
        relationships.append(
            {"party_index": party_index, "relationship": relationship}
        )
    record_activity(matter, "case_relationship_updated", actor_user_id, now=now)


def set_document_plan(
    matter: MutableMapping[str, Any],
    document_id: str,
    plan_status: str,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    _require_choice(plan_status, PLAN_STATUSES, "document plan status")
    item = matter["documents"][document_id]
    item["plan_status"] = plan_status
    if plan_status == "not_selected":
        item["bundle_destinations"] = []
    item["updated_at"] = utc_now_iso(now)
    refresh_dependency_blockers(matter)
    record_activity(
        matter, "document_plan_updated", actor_user_id, document_id=document_id, now=now
    )


def refresh_dependency_blockers(matter: MutableMapping[str, Any]) -> None:
    selected = {
        document_id
        for document_id, item in matter.get("documents", {}).items()
        if item.get("plan_status") != "not_selected"
    }
    for document_id, item in matter.get("documents", {}).items():
        item["dependency_blockers"] = [
            required
            for required in DOCUMENT_REGISTRY[document_id]["requires"]
            if required not in selected
        ]


def set_bundle_destination(
    matter: MutableMapping[str, Any],
    document_id: str,
    bundle_type: str,
    included: bool,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Include or exclude a selected document from an independent bundle plan."""

    _require_choice(bundle_type, BUNDLE_TYPES, "bundle type")
    item = matter["documents"][document_id]
    if item["plan_status"] == "not_selected" and included:
        raise ClinicWorkspaceError("Select the document before adding it to a bundle")
    destinations = set(item.get("bundle_destinations", []))
    if included:
        destinations.add(bundle_type)
    else:
        destinations.discard(bundle_type)
    item["bundle_destinations"] = sorted(destinations)
    item["updated_at"] = utc_now_iso(now)
    record_activity(
        matter,
        "document_bundle_plan_updated",
        actor_user_id,
        document_id=document_id,
        now=now,
    )


def transition_review(
    matter: MutableMapping[str, Any],
    document_id: str,
    new_status: str,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    _require_choice(new_status, REVIEW_STATUSES, "review status")
    item = matter["documents"][document_id]
    current = item["review_status"]
    if new_status == current:
        return
    if new_status not in REVIEW_TRANSITIONS[current]:
        raise ClinicWorkspaceError(
            f"Cannot change review status from {current} to {new_status}"
        )
    if new_status == "ready_for_review" and item.get("dependency_blockers"):
        raise ClinicWorkspaceError("Resolve document dependencies before review")
    if new_status == "ready_for_review" and not any(
        artifact.get("file_reference") and not artifact.get("superseded_at")
        for artifact in item.get("artifacts", [])
    ):
        raise ClinicWorkspaceError("Add or generate a current file before review")
    item["review_status"] = new_status
    item["updated_at"] = utc_now_iso(now)
    record_activity(
        matter,
        f"document_review_{new_status}",
        actor_user_id,
        document_id=document_id,
        now=now,
    )


def record_review_decision(
    matter: MutableMapping[str, Any],
    document_id: str,
    decision: str,
    actor_user_id: int,
    *,
    comment: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Apply a supervisor decision and retain its internal review comment."""

    if decision not in {"approved", "changes_requested"}:
        raise ClinicWorkspaceError("Review decisions must approve or request changes")
    cleaned_comment = " ".join(str(comment or "").split()).strip()
    if decision == "changes_requested" and not cleaned_comment:
        raise ClinicWorkspaceError("A change request must explain what needs to change")
    transition_review(matter, document_id, decision, actor_user_id, now=now)
    timestamp = utc_now_iso(now)
    item = matter["documents"][document_id]
    item.setdefault("review_history", []).append(
        {
            "decision": decision,
            "comment": cleaned_comment or None,
            "reviewer_user_id": actor_user_id,
            "at": timestamp,
            "revision": item["revision"],
        }
    )
    if decision == "approved":
        for artifact in item["artifacts"]:
            if (
                artifact["revision"] == item["revision"]
                and artifact["purpose"] in {"generated_draft", "external_working_draft"}
                and not artifact.get("superseded_at")
            ):
                artifact["eligible_for_bundle"] = True
                artifact["eligible_bundle_types"] = ["court_use", "records"]
            elif (
                artifact["purpose"] in {"signed_copy", "notarized_copy"}
                and artifact.get("verified_at")
                and not artifact.get("superseded_at")
            ):
                artifact["eligible_for_bundle"] = True
                artifact["eligible_bundle_types"] = ["court_use", "records"]


def transition_execution(
    matter: MutableMapping[str, Any],
    document_id: str,
    new_status: str,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    _require_choice(new_status, EXECUTION_STATUSES, "execution status")
    item = matter["documents"][document_id]
    current = item["execution_status"]
    if new_status == current:
        return
    if new_status not in EXECUTION_TRANSITIONS[current]:
        raise ClinicWorkspaceError(
            f"Cannot change execution status from {current} to {new_status}"
        )
    if new_status == "ready_for_signature" and item["review_status"] != "approved":
        raise ClinicWorkspaceError("Supervisor approval is required before signature")
    item["execution_status"] = new_status
    item["updated_at"] = utc_now_iso(now)
    record_activity(
        matter,
        f"document_execution_{new_status}",
        actor_user_id,
        document_id=document_id,
        now=now,
    )


def add_artifact(
    matter: MutableMapping[str, Any],
    document_id: str,
    purpose: str,
    actor_user_id: int,
    *,
    file_reference: Optional[str] = None,
    content_hash: Optional[str] = None,
    supersedes_artifact_id: Optional[str] = None,
    details: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Attach a versioned artifact without treating its claimed purpose as verified."""

    _require_choice(purpose, ARTIFACT_PURPOSES, "artifact purpose")
    item = matter["documents"][document_id]
    timestamp = utc_now_iso(now)
    artifact_details = dict(details or {})
    unsupported_detail_keys = set(artifact_details).difference(ARTIFACT_DETAIL_KEYS)
    if unsupported_detail_keys:
        raise ClinicWorkspaceError(
            "Unsupported artifact details: "
            + ", ".join(sorted(unsupported_detail_keys))
        )
    if supersedes_artifact_id is None and purpose == "generated_draft":
        current_generated = [
            candidate
            for candidate in item["artifacts"]
            if candidate["purpose"] == "generated_draft"
            and not candidate.get("superseded_at")
        ]
        if current_generated:
            supersedes_artifact_id = max(
                current_generated, key=lambda candidate: candidate["version"]
            )["artifact_id"]
    artifact = {
        "artifact_id": str(uuid4()),
        "document_id": document_id,
        "purpose": purpose,
        "version": len(item["artifacts"]) + 1,
        "revision": item["revision"],
        "file_reference": file_reference,
        "content_hash": content_hash,
        "details": artifact_details,
        "uploaded_by_user_id": actor_user_id,
        "uploaded_at": timestamp,
        "verified_by_user_id": None,
        "verified_at": None,
        "supersedes_artifact_id": supersedes_artifact_id,
        "superseded_at": None,
        "superseded_by_artifact_id": None,
        "intake_disposition": None,
        "eligible_for_bundle": False,
        "eligible_bundle_types": [],
    }
    if supersedes_artifact_id:
        previous = next(
            (
                candidate
                for candidate in item["artifacts"]
                if candidate["artifact_id"] == supersedes_artifact_id
            ),
            None,
        )
        if previous is None:
            raise ClinicWorkspaceError("The superseded artifact was not found")
        if previous.get("superseded_at"):
            raise ClinicWorkspaceError("The artifact has already been superseded")
        previous["superseded_at"] = timestamp
        previous["superseded_by_artifact_id"] = artifact["artifact_id"]
        previous["eligible_for_bundle"] = False
        previous["eligible_bundle_types"] = []
    item["artifacts"].append(artifact)
    if purpose == "existing_reference" or purpose == "client_annotated_reference":
        item["source_status"] = "uploaded_reference"
    elif purpose == "external_working_draft":
        item["source_status"] = "external_working_draft"
        item["review_status"] = "in_progress"
    elif purpose == "generated_draft":
        item["source_status"] = "generated"
        item["revision"] += 1
        artifact["revision"] = item["revision"]
        item["review_status"] = "in_progress"
        item["execution_status"] = "draft"
    elif purpose in {
        "signed_copy",
        "notarized_copy",
        "filed_copy",
        "court_returned_copy",
    }:
        item["source_status"] = "confirmed_existing"
        if item["review_status"] == "not_started":
            item["review_status"] = "in_progress"
    item["updated_at"] = timestamp
    record_activity(
        matter, "artifact_added", actor_user_id, document_id=document_id, now=now
    )
    return artifact


def set_artifact_disposition(
    matter: MutableMapping[str, Any],
    document_id: str,
    artifact_id: str,
    disposition: str,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Record how clinic staff will use a received working file."""

    _require_choice(disposition, ARTIFACT_DISPOSITIONS, "artifact disposition")
    artifact = next(
        (
            candidate
            for candidate in matter["documents"][document_id]["artifacts"]
            if candidate["artifact_id"] == artifact_id
        ),
        None,
    )
    if artifact is None:
        raise ClinicWorkspaceError("Artifact not found")
    if artifact.get("superseded_at"):
        raise ClinicWorkspaceError("A superseded artifact cannot be verified")
    if artifact.get("verified_at"):
        raise ClinicWorkspaceError("The artifact has already been verified")
    if artifact["purpose"] not in {
        "existing_reference",
        "external_working_draft",
        "client_annotated_reference",
    }:
        raise ClinicWorkspaceError("This received file does not need an intake disposition")
    artifact["intake_disposition"] = disposition
    if disposition == "use_exact_file":
        artifact["purpose"] = "external_working_draft"
        matter["documents"][document_id]["source_status"] = "external_working_draft"
        matter["documents"][document_id]["review_status"] = "in_progress"
    elif disposition == "update_answers_and_regenerate":
        matter["documents"][document_id]["review_status"] = "in_progress"
    record_activity(
        matter,
        "artifact_disposition_recorded",
        actor_user_id,
        document_id=document_id,
        now=now,
    )
    return artifact


def verify_artifact(
    matter: MutableMapping[str, Any],
    document_id: str,
    artifact_id: str,
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Verify a received artifact and apply only the corresponding safe transition."""

    item = matter["documents"][document_id]
    artifact = next(
        (
            candidate
            for candidate in item["artifacts"]
            if candidate["artifact_id"] == artifact_id
        ),
        None,
    )
    if artifact is None:
        raise ClinicWorkspaceError("Artifact not found")
    timestamp = utc_now_iso(now)
    artifact["verified_by_user_id"] = actor_user_id
    artifact["verified_at"] = timestamp
    purpose = artifact["purpose"]
    if purpose == "signed_copy" and item["execution_status"] != "filed":
        item["execution_status"] = "signed"
    elif purpose == "notarized_copy" and item["execution_status"] != "filed":
        item["execution_status"] = "notarized"
    elif purpose == "filed_copy":
        item["execution_status"] = "filed"
        item["delivery_status"] = "filed"
    elif purpose == "court_returned_copy":
        if artifact.get("details", {}).get("court_outcome") in {
            "rejected",
            "needs_followup",
        }:
            item["execution_status"] = "needs_revision"
        else:
            item["execution_status"] = "filed"
            item["delivery_status"] = "filed"
    elif purpose in {"external_working_draft", "generated_draft"}:
        artifact["eligible_for_bundle"] = item["review_status"] == "approved"
        artifact["eligible_bundle_types"] = (
            ["court_use", "records"] if artifact["eligible_for_bundle"] else []
        )
    if purpose in {"signed_copy", "notarized_copy"}:
        artifact["eligible_for_bundle"] = True
        artifact["eligible_bundle_types"] = ["records"]
        if item["review_status"] == "approved":
            artifact["eligible_bundle_types"].insert(0, "court_use")
    elif purpose in {"filed_copy", "court_returned_copy"}:
        artifact["eligible_for_bundle"] = True
        artifact["eligible_bundle_types"] = ["records"]
    item["updated_at"] = timestamp
    record_activity(
        matter, "artifact_verified", actor_user_id, document_id=document_id, now=now
    )
    return artifact


def bundle_artifacts(
    matter: Mapping[str, Any], bundle_type: str
) -> List[Dict[str, Any]]:
    """Return one current, eligible artifact for each document in a bundle plan."""

    _require_choice(bundle_type, BUNDLE_TYPES, "bundle type")
    selected: List[Dict[str, Any]] = []
    for document_id in DOCUMENT_REGISTRY:
        item = matter["documents"][document_id]
        if bundle_type not in item.get("bundle_destinations", []):
            continue
        candidates = [
            artifact
            for artifact in item["artifacts"]
            if artifact.get("eligible_for_bundle")
            and bundle_type in artifact.get("eligible_bundle_types", [])
            and not artifact.get("superseded_at")
            and artifact.get("file_reference")
        ]
        if candidates:
            selected.append(max(candidates, key=lambda artifact: artifact["version"]))
    return selected


def matter_closeout_blockers(matter: Mapping[str, Any]) -> List[str]:
    """List planned documents that are neither approved nor already filed."""

    return [
        DOCUMENT_REGISTRY[document_id]["title"]
        for document_id, item in matter.get("documents", {}).items()
        if item.get("plan_status") != "not_selected"
        and item.get("review_status") != "approved"
        and item.get("execution_status") != "filed"
    ]


def content_digest(content: bytes) -> str:
    """Return a stable SHA-256 digest for duplicate-file detection."""

    return sha256(content).hexdigest()


def affected_documents_for_change(
    matter: Mapping[str, Any], document_id: str
) -> List[str]:
    """Return selected documents whose content may share the changed facts."""

    if document_id not in DOCUMENT_REGISTRY:
        raise ClinicWorkspaceError(f"Unsupported document: {document_id}")
    if document_id == "joint_petition":
        affected = set(DOCUMENT_REGISTRY)
    else:
        affected = set(CHANGE_IMPACT_MAP.get(document_id, {document_id}))
    return [
        candidate
        for candidate in DOCUMENT_REGISTRY
        if candidate in affected
        and matter["documents"][candidate]["plan_status"] != "not_selected"
    ]


def mark_fact_changes(
    matter: MutableMapping[str, Any],
    affected_document_ids: Sequence[str],
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Invalidate review and execution state for documents affected by changed facts."""

    for document_id in affected_document_ids:
        if document_id not in DOCUMENT_REGISTRY:
            raise ClinicWorkspaceError(f"Unsupported document: {document_id}")
    for document_id in affected_document_ids:
        item = matter["documents"][document_id]
        if item["review_status"] == "approved":
            item["review_status"] = "in_progress"
        if item["execution_status"] in {
            "ready_for_signature",
            "signed",
            "notarized",
            "filed",
        }:
            item["execution_status"] = "needs_revision"
        for artifact in item["artifacts"]:
            if artifact["purpose"] in {"filed_copy", "court_returned_copy"}:
                artifact["eligible_bundle_types"] = ["records"]
                artifact["eligible_for_bundle"] = True
            else:
                artifact["eligible_bundle_types"] = []
                artifact["eligible_for_bundle"] = False
        item["updated_at"] = utc_now_iso(now)
        record_activity(
            matter,
            "document_facts_changed",
            actor_user_id,
            document_id=document_id,
            now=now,
        )


def safe_matter_summary(matter: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a matter into the explicit non-confidential dashboard allowlist."""

    active_members = [
        member for member in matter.get("team_members", []) if member.get("active")
    ]
    team_user_ids = sorted({member["user_id"] for member in active_members})
    supervisor_user_ids = sorted(
        {
            member["user_id"]
            for member in active_members
            if member.get("matter_role") == "supervisor"
        }
    )
    blocked_count = sum(
        1
        for item in matter.get("documents", {}).values()
        if item.get("dependency_blockers")
        or item.get("execution_status") == "needs_revision"
    )
    summary = {
        "clinic_workspace": True,
        "matter_id": matter["matter_id"],
        "safe_label": matter["safe_label"],
        "title": matter["safe_label"],
        "auto_title": matter["safe_label"],
        "description": matter.get("next_action", ""),
        "owner_user_id": matter["owner_user_id"],
        "team_user_ids": team_user_ids,
        "supervisor_user_ids": supervisor_user_ids,
        "case_posture": matter.get("case_posture", "unselected"),
        "overall_status": matter.get("overall_status", "active"),
        "next_action": matter.get("next_action", "review_matter"),
        "blocked_count": blocked_count,
        "due_date": matter.get("due_date"),
        "updated_at": matter.get("updated_at"),
        "schema_version": matter.get("schema_version", SCHEMA_VERSION),
    }
    assert_safe_metadata(summary)
    return summary


def assert_safe_metadata(metadata: Mapping[str, Any]) -> None:
    extra_keys = set(metadata).difference(SAFE_METADATA_KEYS)
    if extra_keys:
        raise ClinicWorkspaceError(
            "Unsafe dashboard metadata keys: " + ", ".join(sorted(extra_keys))
        )


def filter_visible_summaries(
    summaries: Iterable[Mapping[str, Any]],
    user_id: int,
    privileges: Iterable[str],
    *,
    status: Optional[str] = None,
    needs_review: bool = False,
    offset: int = 0,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """Filter already-safe summaries for a paginated dashboard view."""

    if limit < 1 or limit > 100:
        raise ClinicWorkspaceError("Dashboard page size must be between 1 and 100")
    privilege_set = set(privileges)
    visible: List[Dict[str, Any]] = []
    for raw_summary in summaries:
        summary = dict(raw_summary)
        assert_safe_metadata(summary)
        if not privilege_set.intersection({"clinic_admin", "admin"}) and user_id not in summary.get(
            "team_user_ids", []
        ):
            continue
        if not has_clinic_privilege(privilege_set):
            continue
        if status and summary.get("overall_status") != status:
            continue
        if needs_review and summary.get("next_action") != "supervisor_review":
            continue
        visible.append(summary)
    visible.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return visible[max(offset, 0) : max(offset, 0) + limit]


def close_matter(
    matter: MutableMapping[str, Any],
    actor_user_id: int,
    *,
    reason: str = "completed",
    now: Optional[datetime] = None,
) -> None:
    _require_choice(reason, CLOSURE_REASONS, "closure reason")
    if matter.get("overall_status") == "closed":
        raise ClinicWorkspaceError("The matter is already closed")
    if reason == "completed" and matter_closeout_blockers(matter):
        raise ClinicWorkspaceError(
            "A completed matter cannot have unfinished planned documents"
        )
    timestamp = utc_now_iso(now)
    matter["overall_status"] = "closed"
    matter["next_action"] = "none"
    matter["closed_at"] = timestamp
    matter["closed_by_user_id"] = actor_user_id
    matter["closure_reason"] = reason
    record_activity(matter, "matter_closed", actor_user_id, now=now)


def reopen_matter(
    matter: MutableMapping[str, Any],
    actor_user_id: int,
    *,
    now: Optional[datetime] = None,
) -> None:
    if matter.get("overall_status") != "closed":
        raise ClinicWorkspaceError("Only a closed matter can be reopened")
    matter["overall_status"] = "active"
    matter["next_action"] = "review_matter"
    matter["closed_at"] = None
    matter["closed_by_user_id"] = None
    matter["closure_reason"] = None
    record_activity(matter, "matter_reopened", actor_user_id, now=now)


def document_registry_for_display() -> List[Dict[str, Any]]:
    """Return a serialization-safe registry for interview choice lists."""

    return [
        {"document_id": document_id, **deepcopy(definition)}
        for document_id, definition in DOCUMENT_REGISTRY.items()
    ]
