# Operations and account model

> **Status is implementation and deployment contract.** This is not a claim about
> the configuration of any current Suffolk Docassemble server.

## Operator responsibilities

Clinic operators own the following responsibilities.

- staff account invitation and deactivation.
- assignment of clinic privileges.
- the supervisor/student roster.
- deployment configuration and package updates.
- storage, backup, retention, and deletion policy.
- incident response.
- periodic review of active and closed matter access.

The package owns matter-level access checks and workflow behavior. It does not
grant server privileges or change global authentication settings.

## Clinic administrator view

An account with `clinic_admin` can list the safe summary of every clinic matter
and can open a matter subject to the application policy. This supports caseload
oversight and recovery from an assignment problem without exposing client facts
in the dashboard index.

This release does not provide a complete operations console. The following
capabilities remain separate operator work.

- identify a stalled or repeatedly failing generation job.
- inspect package and dependency health without entering a matter.
- repair roster or assignment records through a guided workflow.
- collect a privacy-safe diagnostic bundle for support.
- link users to role-specific help and escalation instructions.
- report aggregate queue, performance, and error trends.

These tools should be built as an administrator-only surface over safe status
projections. They should not turn the caseload dashboard into a view of full
session answers or unrestricted server administration.

## Staff registration

The recommended staff-registration flow follows these steps.

1. A clinic administrator invites a staff member through Docassemble.
2. The invitation is assigned the appropriate custom clinic privilege.
3. The staff member completes registration and the configured authentication
   requirements.
4. An owner, assigned supervisor, or clinic administrator adds the person's
   stable user ID to a matter with a collaborator, supervisor, or viewer role.
5. The assigned person opens the protected matter link through an approved
   clinic communication channel.
6. The workspace checks both the server privilege and stored matter membership.

Students do not create server accounts or grant server privileges. The current
team screen accepts a stable user ID. The target account must already exist and
have the matching clinic privilege. Assignment never elevates a server account.

## Supervisor assignment

The current version assigns supervisors per matter. A server-managed roster and
default-supervisor inheritance remain deployment follow-up work.

Changing supervisors must.

- add the new supervisor's matter membership.
- preserve prior review and activity history.
- remove the former supervisor's access when appropriate.
- identify documents awaiting review so they are not stranded.

## Account offboarding

When clinic access ends, operators complete these steps.

1. Deactivate or remove the person's clinic privilege at the server level.
2. Mark the roster entry inactive.
3. Reassign owned matters and pending document tasks.
4. Remove matter memberships that are no longer required.
5. Confirm that supervisor queues have no orphaned matters.
6. Preserve activity history under the stable user ID.

Removing an account must not silently delete shared matters.

## Matter closure

Closing a matter makes it read-only by default and records the following data.

- closure reason.
- closure date.
- closing actor.
- preserved filing and execution state.
- preserved unresolved or intentionally deferred document state.

Only a clinic administrator reopens a matter, and the action creates an activity
event. Archive and deletion are different operations. Deletion must follow the approved
retention policy and must not be inferred from ordinary closure.

## Deployment prerequisites

Before real client use, operators must confirm the following protections.

- production authentication and registration settings.
- required multi-factor authentication or identity provider behavior.
- custom clinic privileges.
- HTTPS and secure-cookie configuration.
- database, uploaded-file, generated-file, and backup protections.
- email behavior for any client or signer release.
- retention and deletion rules.
- monitoring that does not leak case data.
- a tested rollback and recovery process.

Local and CI development use synthetic data and must not call shared Suffolk
interview servers.

## Isolated runtime certification

The accepted certification environment uses the pinned Docassemble image from
`tests/certification/baseline.json`, currently:

```text
jhpyle/docassemble@sha256:c0b0a707a6cd2149d5777ee83af1ea1de544210e597371eac93e67a1503c395c
```

Run the container on a loopback-only port, install this package and its pinned
interview dependencies, verify the runtime manifest, and then use synthetic
accounts and matter data. Do not point the runtime drivers at a shared,
staging, or production server.

After the server is ready, the clinic driver accepts the following phases.

```bash
python3 tests/clinic_workspace/runtime_lifecycle_driver.py \
  --server http://127.0.0.1:8088 \
  --api-key "$ISOLATED_DOCASSEMBLE_API_KEY" \
  --artifacts test-artifacts/runtime \
  --report test-artifacts/runtime/clinic-runtime-report.json \
  --phase all
```

- `all` prepares every supported document and then runs the review, execution,
  bundle, closure, and reopen lifecycle.
- `lifecycle` runs the role and document-state lifecycle on a smaller fixture.
- `answer-review` prepares the care-or-custody affidavit and one financial
  statement, edits a canonical child answer, and checks the financial
  collection routes.
- `restart` reopens a named existing session after an actual container restart
  and verifies the stored matter state and dashboard filters.

The API key must belong only to the disposable certification server. Reports,
screenshots, and HTML captures must contain synthetic data and must not contain
the key or generated account passwords.

## Recovery boundary

An ordinary container restart preserves the tested session state because the
database and file volumes remain mounted. That is not a backup test. Operators
must still prove restoration from an independent backup, document recovery time
and recovery point expectations, and verify uploaded and generated files after
restoration.

## Documentation ownership

Operator-facing configuration examples must use placeholders. Actual secrets,
server URLs, API keys, user lists, and matter data belong in approved secure
systems, not this repository.

Every deployment-affecting change must update this guide or link to the
canonical external runbook. Once a production runbook exists, this file should
identify its owner and location without duplicating secrets or volatile values.
