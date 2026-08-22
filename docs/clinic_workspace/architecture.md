# Clinic workspace architecture

> **Status: implemented and runtime-certified in an isolated environment.** This
> document records the current architecture and the boundaries later changes
> must preserve.

## Product shape

```text
Clinic caseload dashboard
        |
        v
Persistent matter workspace
        |
        +-- Filing plan and dependencies
        +-- Shared case intake
        +-- Document work items
        +-- Supervision and review
        +-- Signatures, notarization, and filing
        +-- Court and records bundles
```

Each clinic matter is one persistent Docassemble interview session. The matter
workspace is the canonical store for its detailed facts and workflow state. A
separate control-panel-style interview lists safe summaries of matters the
current staff user may access.

## Entrypoints and integration

The package exposes two product surfaces without replacing the public
interview.

- `main_joint_petition.yml` remains the public or pro se entrypoint.
- `main_clinic_dashboard.yml` is the clinic staff entrypoint and always opens
  on the caseload dashboard.
- `main_student_packet.yml` is an internal matter route. A fresh request without
  the dashboard creation token returns to the dashboard.

The clinic matter interview includes the existing joint-petition and temporary-
orders interviews as document modules. The clinic parent reasserts its own
navigation sections on every request, calls a selected child workflow, and then
returns the student to the same matter. This preserves one canonical set of
answers while keeping the public and clinic entry experiences distinct.

## Actor model

The implementation must not conflate these three concepts.

1. **Platform privilege.** whether an authenticated account may enter the clinic
   application, such as `clinic_student`, `clinic_supervisor`, or `clinic_admin`.
2. **Matter membership.** what a staff user may do in one matter, such as owner,
   collaborator, assigned supervisor, or read-only viewer.
3. **Case relationship.** whether a person is a represented client, an assisted
   party, the other spouse, or a purpose-limited signer.

The two spouses are legal parties. Either, both, or neither may be a clinic
client depending on the approved service model. The interview must ask and store
that relationship explicitly.

## Main components

### Clinic dashboard

The dashboard lists summaries, never complete answer dictionaries. The current
views include the following categories.

- all assigned matters.
- matters that need review.
- closed matters.

Clinic administrators may list every safe matter summary. Student and
supervisor accounts see sessions associated with their accounts and still pass
the stored matter-membership check when opening a matter. The implemented
filters cover assigned matters, matters awaiting review, and closed matters.
Blocked, upcoming, and recently updated views remain product refinements.

The clinic administrator view is a global caseload view, not a server
troubleshooting console. Generation diagnostics, stuck-session indicators,
account and roster repair, support links, and operational audit tools require a
separate administrator surface. That surface must use the same safe metadata
boundary and must not expose full answer dictionaries in a list view.

Dashboard queries must be paginated and scoped to the authenticated user's
matter memberships.

### Matter workspace

The workspace owns the following data and workflow state.

- matter identity and safe display label.
- team membership and assigned supervisor.
- case posture and filing plan.
- shared party, child, court, and financial facts.
- document work items and dependency state.
- internal review comments and decisions.
- artifact versions and reference uploads.
- missing-information and blocker lists.
- activity history.
- closure/archive state.

### Document adapters

The clinic parent calls supported child `interview_order_*` blocks through
explicit adapters. Child modules do not own clinic navigation, progress, matter
membership, final review, or bundle selection.

The registry and adapter for each document family define the following contract.

- prerequisites and dependency warnings.
- the variables the child flow requires.
- its clinic-owned answer-review targets and focused generation route.
- generation and validation hooks.
- facts whose change invalidates an approved or executed version.
- allowed artifact purposes.
- court-use and records-bundle rules.

## Domain objects

### Matter

| Field | Example or type |
| --- | --- |
| `matter_id` | Stable UUID |
| `safe_label` | Clinic-safe identifier |
| `case_posture` | `new_joint_1a` |
| `overall_status` | `active` |
| `owner_user_id` | Docassemble user ID |
| `team_members` | Membership records |
| `party_relationships` | Party-to-clinic relationship records |
| `filing_plan` | Matter task and update time |
| `documents` | Document work items keyed by document ID |
| `internal_notes` | Confidential collaboration notes |
| `activity` | Non-confidential event records |
| `schema_version` | `2` |

### Team member

| Field | Example or type |
| --- | --- |
| `user_id` | Stable Docassemble user ID |
| `matter_role` | `owner`, `collaborator`, `supervisor`, or `viewer` |
| `active` | Boolean |
| `assigned_at` | UTC timestamp |
| `assigned_by_user_id` | Stable Docassemble user ID |

### Document work item

| Field | Example or type |
| --- | --- |
| `document_id` | `separation_agreement` |
| `plan_status` | `prepare_now` |
| `source_status` | `generated` |
| `execution_status` | `draft` |
| `review_status` | `in_progress` |
| `delivery_status` | `not_selected` |
| `assigned_user_id` | Stable Docassemble user ID or null |
| `bundle_destinations` | Any combination of `court_use` and `records` |
| `dependency_blockers` | Required document IDs |
| `artifacts` | Versioned artifact records |
| `revision` | Integer |

### Artifact

| Field | Example or type |
| --- | --- |
| `artifact_id` | Stable UUID |
| `document_id` | Supported document ID |
| `purpose` | `client_annotated_reference` |
| `version` | Integer |
| `uploaded_by_user_id` | Stable Docassemble user ID |
| `uploaded_at` | UTC timestamp |
| `verified_by_user_id` | Stable Docassemble user ID or null |
| `verified_at` | UTC timestamp or null |
| `supersedes_artifact_id` | Prior artifact UUID or null |
| `superseded_by_artifact_id` | Newer artifact UUID or null |
| `eligible_bundle_types` | Any combination of `court_use` and `records` |

The actual file object remains in the protected matter session. The dashboard
index does not contain file contents or file URLs.

## Persistence boundary

Interview YAML calls a narrow repository adapter rather than querying session
storage directly.

```python
persist_current_matter_summary()
list_current_user_matter_summaries()
snapshot_generated_artifact()
```

The implementation stores the complete matter in the current Docassemble
multi-user session and uses narrowly scoped AssemblyLine session metadata for
dashboard queries. Container-restart certification confirms that the matter,
membership, notes, artifacts, and review state persist across an ordinary
application restart. A future database-backed repository can preserve the same
boundary.

The dashboard query is deliberately reevaluated whenever the dashboard opens.
Creating or changing a matter in another interview session therefore does not
leave a previously opened caseload view with a completed, stale result.

Access policy is a separate interface. Changing the storage backend must not
change who can list, view, edit, review, release, download, or close a matter.

## Safe dashboard metadata

Searchable metadata may include the following fields.

- matter UUID and clinic-safe label.
- owner, collaborator, and supervisor user IDs.
- posture and workflow status.
- next action and blocker count.
- non-confidential due date.
- last-updated timestamp.
- schema version.

It must not include client names, addresses, dates of birth, financial values,
document text, signatures, internal notes, or file URLs.

## Implementation files

```text
docassemble/MATC1ADivorceJointPetition/data/questions/
  main_clinic_dashboard.yml
  main_student_packet.yml
docassemble/MATC1ADivorceJointPetition/
  clinic_workspace.py
  clinic_repository.py

docassemble/MATC1ADivorceJointPetition/data/static/
  clinic_workspace.css

tests/clinic_workspace/
  test_clinic_workspace.py
  test_clinic_repository.py
  test_clinic_source.py
  benchmark_dashboard.py
```

The YAML entrypoints own presentation and Docassemble events. The pure Python
domain module owns state and authorization rules. The repository module is the
only code that reads dashboard session metadata or freezes generated files.
