# Access and privacy

> **Status is implementation and deployment contract.** Application-level checks
> are implemented. Production use still depends on confirmation of the target
> server's authentication, storage, backup, and retention configuration.

## Security boundary

The internal matter workspace is for authenticated clinic staff. Clients,
other parties, and outside signers do not join that session.

The current version has no client-facing account or release route. Staff add
files received from a client, other party, signer, notary, or court. Any future
client release must be separate and purpose-limited. Possession of a workspace
URL is never a substitute for staff authorization.

## Authentication and registration

The recommended server configuration has the following requirements.

- Disable public self-registration.
- Invite staff accounts through Docassemble administration.
- Assign `clinic_student`, `clinic_supervisor`, or `clinic_admin` privileges.
- Require multi-factor authentication when the server's login method supports
  it.
- Deactivate accounts promptly when clinic access ends.

Authentication and account creation are server operations. The interview
package must not silently create users, elevate privileges, or rewrite global
authentication configuration.

The package must fail closed when the user is not logged in or does not have an
allowed clinic privilege.

## Authorization

Platform privilege permits entry to the product. Matter membership determines
access to an individual case.

Protected events and status mutations call the access policy. Artifact links are
rendered only after the matter-access gate succeeds. Direct-download and action
URL abuse remain required runtime security tests. Hiding a button is not
authorization.

Current policy operations are shown below. Their implementation receives the
matter before the user identifier because authorization is evaluated against
the loaded matter record.

```python
can_view_matter(matter, user_id, privileges)
can_edit_facts(matter, user_id, privileges)
can_review_document(matter, user_id, privileges)
can_manage_team(matter, user_id, privileges)
can_close_matter(matter, user_id, privileges)
can_add_internal_note(matter, user_id, privileges)
```

Stable Docassemble user IDs are canonical for access. Email may help locate an
account, but changing or matching an email address must not grant access by
itself.

## Privilege scope

Clinic staff should use custom clinic privileges. The built-in `admin`,
`developer`, and `advocate` privileges have broader server meanings and should
not be granted merely to use this product.

- `clinic_student` permits use of the application and assigned matters.
- `clinic_supervisor` permits use of assigned matters and supervisor review actions.
- `clinic_admin` permits management of the clinic roster and clinic matter access.
- Server `admin` remains reserved for actual server administrators.

## Multi-user storage decision

Docassemble's native multi-user session model makes collaboration possible but
does not use its ordinary per-user server-side answer encryption. The production
operator must therefore confirm the following protections.

- HTTPS and secure cookies.
- database and file-storage protection.
- backup access and encryption.
- administrator access controls.
- logging and monitoring boundaries.
- retention and deletion policy.
- incident-response ownership.

This project can be built and tested locally with synthetic data before those
deployment decisions are complete. Real client data must not be used until they
are confirmed.

## Metadata minimization

The dashboard index is searchable and therefore intentionally narrow. It may
contain staff user IDs, a clinic-safe matter label, status, blocker counts, due
dates, and timestamps. It must not contain substantive client facts, document
contents, signatures, internal notes, or file links.

Application and test logs must not include the following data.

- client names or contact information.
- financial facts.
- document text.
- uploaded filenames when they reveal client identity.
- session identifiers.
- authentication tokens.
- invitation links.

## Future client and signer releases

A future client release is separate from the internal workspace and has an
explicit purpose, expiration, and disclosure set. Permitted purposes may
include the following actions.

- review one supervisor-approved draft.
- answer a bounded set of missing questions.
- sign one identified document.
- download an approved records bundle.

The release must not expose internal comments, unrelated documents, or the
workspace session key. Returned answers or artifacts enter an intake queue and
require staff review before altering canonical facts or statuses.

Remote participant identity strength is a deployment choice. A one-use email
link proves access to that mailbox, not legal identity. Sensitive remote actions
may require an authenticated client account or another approved verification
step.

## Access tests

Unit tests prove the domain denials for unprivileged and unrelated staff
accounts. The isolated authenticated lifecycle proves that an unrelated student
is denied, a collaborator can enter an assigned matter, a supervisor can review
and close it, an owner cannot edit it after closure, and a clinic administrator
can reopen it.

Before production use, the exhaustive runtime access matrix must also prove
that these actors cannot access or mutate an internal matter.

- an unauthenticated visitor.
- a logged-in user without a clinic privilege.
- an unrelated student.
- an unassigned supervisor.
- a removed collaborator.
- a client or other party.
- an outside signer.

An exhaustive collaboration and adversarial-access matrix is follow-on work,
but the baseline denial cases are part of the first implementation.
