# Clinic workspace documentation

> **Status: implemented and runtime-certified in an isolated environment.** The
> workspace has not been deployed for client work. The existing pro se interview
> remains a separate entrypoint.

The clinic workspace is a clinic-only product for planning, preparing,
reviewing, executing, and tracking a supported Massachusetts 1A divorce packet.
It preserves the existing pro se interview while adding a persistent matter
workspace and caseload dashboard for authenticated clinic staff.

## Documentation map

### Student clinicians

- [Student workflow](student_workflow.md) describes the implemented product
  flow, including adding client-provided files, correcting answers,
  regenerating documents, requesting review, and recording signed or filed
  copies.
- [Document and upload lifecycle](document_lifecycle.md) explains which kind
  of upload to use and what happens after a replacement or correction.

### Clinic operators

- [Operations and account model](operations.md) covers staff registration,
  privileges, roster management, deployment prerequisites, closure, and
  retention decisions.
- [Access and privacy](access_and_privacy.md) defines the authorization boundary,
  client-participation model, metadata rules, and immediate security requirements.

### Developers

- [Architecture](architecture.md) describes components, domain objects, parent/child
  interview boundaries, persistence adapter, and implementation files.
- [Document and upload lifecycle](document_lifecycle.md) defines canonical-data,
  versioning, invalidation, and artifact rules.
- [Testing and performance](testing_and_performance.md) describes integration coverage,
  access-control tests, benchmark fixtures, and future certification work.

## Product boundaries

The complete product target includes the following capabilities.

- A persistent clinic matter workspace
- A caseload dashboard for students and supervisors
- Assignments, review decisions, comments, and activity history
- Full integration of every supported document family
- Reference, execution, and filed-copy uploads
- Separate court-use and student/client-record bundles
- Baseline authorization tests and performance tests
- Closure and archive states

The current version does not require an external case-management database, a
general-purpose client portal, automatic extraction from uploaded documents,
e-filing, or a remote-notarization service. The architecture must leave clean
integration boundaries for those later capabilities.

## Documentation rules

- Label planned and implemented behavior explicitly.
- Update the relevant audience document in the same change that alters behavior.
- Keep one canonical explanation for each decision and link to it elsewhere.
- Describe why a boundary exists, especially for access, uploads, and document
  invalidation.
- Do not put real client data, credentials, session identifiers, or production
  configuration values in documentation or examples.
- Treat user-facing wording as product behavior and cover it in walkthroughs.

## Current decisions

- `main_joint_petition.yml` remains the ordinary pro se entrypoint.
- A separate `main_student_packet.yml` owns clinic routing, review, and bundles.
- A separate clinic dashboard lists matters visible to the current staff
  member.
- Clients and outside signers will not join the internal staff workspace.
- Uploads never silently replace canonical answers or enter a filing bundle.
- Source, execution, review, and delivery status remain distinct.
- The detailed matter record remains in a multi-user Docassemble session. Safe,
  searchable summaries sit behind a repository adapter so storage can change
  without changing interview code or authorization policy.
