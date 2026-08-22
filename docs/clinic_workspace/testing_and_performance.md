# Testing and performance

> **Status: current as of 2026-08-22.** The combined-interview certification
> remains the source-coverage baseline. The clinic suite adds domain,
> repository, source-contract, authenticated lifecycle, restart, document, and
> performance coverage.

## Current automated coverage

The local suite passes 64 clinic tests and 97 combined-interview certification
tests. The clinic workflow runs the clinic model and source tests and uploads
the dashboard model benchmark on pull requests and manual dispatches. The full
Docassemble browser certification remains an isolated manual run because it
creates users, sessions, files, and generated documents inside a disposable
server.

The model benchmark exercises in-memory safe-summary filtering with synthetic
sets up to 5,000 matters. At 5,000 summaries, assigned-matter filtering measures
0.003421 seconds at p95 and review filtering measures 0.003510 seconds at p95.
This benchmark does not include a database, HTTP, templates, or a browser.

The authenticated browser benchmark measures the rendered application on a
loopback-only Docassemble container with 6 GB of memory and two Celery workers.
Ten dashboard samples measure 0.7994 seconds at p95; ten authorized matter-open
samples measure 0.6205 seconds at p95; and four dashboard-filter samples measure
0.2958 seconds at p95. These results are below the initial budgets.

## Certified runtime coverage

The isolated clinic run proves the following behavior.

- All 13 supported document work items generate successfully.
- The child interviews return to the clinic parent without taking over clinic
  navigation.
- One synthetic all-document matter traverses 298 rendered workflow screens.
- A separate visible-action crawl checks 24 dashboard, matter, document, and
  bundle routes, including first-use and filtered empty states.
- A generated draft is submitted, returned with changes, corrected through the
  clinic answer-review screen, regenerated, resubmitted, and approved.
- A targeted browser run edits a child answer through the care-or-custody card
  and renders the financial income, expense, asset, liability, and schedule
  collection routes.
- A signed copy is uploaded and verified.
- Separate court-use and records bundles are generated.
- An assigned supervisor closes the matter, the owner receives a read-only
  view, and a clinic administrator reopens it.
- Owner, collaborator, supervisor, unrelated student, and administrator roles
  exercise their expected lifecycle paths.
- A full container restart preserves three artifact revisions, both bundle
  destinations, review and execution state, one internal note, and active owner,
  collaborator, and supervisor memberships.

## Test layers

### Static and unit tests

- access-policy decisions.
- state-transition validity.
- role and relationship separation.
- dependency resolution.
- safe dashboard metadata allowlist.
- artifact versioning and supersession.
- fact-change invalidation.
- bundle eligibility.
- repository interface behavior.

### Runtime scenarios

- create, leave, and resume a matter.
- assign a collaborator and supervisor.
- complete shared intake.
- prepare every supported document family.
- submit, request changes, regenerate, and approve.
- upload each supported artifact purpose.
- verify signed, notarized, filed, and rejected returns.
- produce exact court and records bundles.
- close and reopen a matter.

### Current authorization scenarios

The domain tests cover privilege and membership denials. The authenticated
browser run covers unrelated-student denial and the positive owner,
collaborator, supervisor, and administrator paths. The following broader matrix
remains required before production use.

- unauthenticated users.
- users without clinic privileges.
- unrelated students.
- unassigned supervisors.
- removed collaborators.
- clients and other parties.
- outside signers.

An exhaustive role/action/concurrency matrix is a follow-on certification, not
a reason to omit the baseline denial tests.

## Performance design

The dashboard must satisfy the following design constraints.

- query summary metadata rather than full answer dictionaries.
- paginate results.
- filter before rendering.
- avoid document generation and file loading.
- avoid client-identifying display metadata.
- load full matter state only after an authorized user opens one matter.

## Benchmark fixtures

Use synthetic data only. Seed isolated local or CI databases with the following
fixture sizes.

- 100 matters for a functional baseline.
- 500 matters for ordinary scale.
- 1,000 matters for the initial capacity target.

Distribute matters across multiple students and supervisors, with active,
blocked, review, filed, and closed states.

The current benchmark measures safe-summary construction and filtering. Runtime
work must also measure the following operations.

- initial dashboard response.
- My matters.
- supervisor review queue.
- keyword search.
- status filters.
- opening a matter.
- recording a status transition.
- adding metadata for a new artifact.

## Initial budgets

The documented reference Docker environment has the following initial budgets.

- dashboard response at 1,000 indexed matters, less than 2 seconds at p95.
- common filters and supervisor queue, less than 1.5 seconds at p95.
- authorized matter open, less than 2 seconds at p95.
- ordinary status mutation, less than 1 second at p95.

Absolute CI timing can be noisy. Store benchmark results as machine-readable
artifacts and also flag a sustained regression greater than 20 percent from the
accepted baseline.

The runtime benchmark report must record image digest, package versions, seed,
fixture size, host characteristics, and query counts so results are comparable.

## Future certification tickets

- exhaustive collaboration and access permutations.
- concurrent editing, task locks, and stale-write behavior.
- adversarial URL/action/download testing.
- backup and restoration proof.
- production-scale load characterization.
- accessibility and polished student/supervisor walkthroughs.

All local and CI tests must avoid shared Suffolk Docassemble servers.

## Environment isolation

The accepted runtime results came from a private VM and a loopback-only Docker
port. No Suffolk or LIT Lab server was contacted. This isolation is a test
requirement, not merely a convenience: certification creates disposable users,
matters, uploads, and generated files.
