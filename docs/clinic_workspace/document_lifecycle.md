# Document and upload lifecycle

> **Status: implemented and runtime-certified in an isolated environment.** This
> document is the canonical rule set for received files, answer corrections,
> regeneration, execution copies, and filing copies.

## The short answer about re-uploading

Yes. A student may add a file received from a client, another party, a notary,
or the court. The student should not need to hunt through unrelated interview
screens to decide what to do with it.

The document card provides an **Add received file** action. The student
chooses why the file is being added from the supported purposes below.

- existing document for reference.
- external working draft or client-annotated copy.
- signed copy.
- notarized copy.
- court-filed copy.
- court-returned copy.

The choice determines the next checklist and possible status change. Uploading
alone never certifies that the document is complete, signed, notarized, or filed.

## Separate status dimensions

Each document records source, review, execution, plan, and bundle state separately.

### Source

- `confirmed_existing`
- `uploaded_reference`
- `generated`
- `external_working_draft`

### Review

- `not_started`
- `in_progress`
- `ready_for_review`
- `changes_requested`
- `approved`

### Execution

- `draft`
- `ready_for_signature`
- `signed`
- `notarized`
- `needs_revision`
- `filed`

### Plan

- `not_selected`
- `prepare_now`
- `later`

### Bundle destinations

- `court_use`
- `records`

A document may enter both bundles. Bundle destinations are independent of its
preparation status.

A file can therefore be an uploaded reference without being treated as an
approved or filed document.

## Canonical facts versus files

The matter's structured answers are canonical for generated documents. An
uploaded PDF or DOCX does not silently populate or overwrite those answers.

If a client sends a filled or annotated document, the student chooses whether
to retain it only as a reference, use that exact file as the working document,
or update canonical answers and regenerate. The last option opens the clinic's
document-specific answer list. It does not send the student into the combined
interview or a child interview's standalone navigation.

This separation provides the following safeguards.

- the student sees which facts will change.
- shared facts remain consistent across every affected form.
- the system can identify other documents that need regeneration.
- provenance is preserved.
- an unreviewed upload cannot silently alter a filing packet.

Automatic extraction or comparison may be added later, but only after separate
form-specific evaluation, provenance, human confirmation, and retention review.

## Updating answers without field hunting

Every planned document begins with **Answer questions and create draft**. After
a draft exists, its card offers **Review or update answers**. That action opens
a clinic-owned list of the document's canonical answer targets, including the
main party, court, child, financial, agreement, and execution fields used by
that form.

```text
Review or update answers
  -> Choose a labeled answer or collection
  -> Save the correction
  -> Return to the same answer list
  -> Select Done reviewing answers
  -> Regenerate draft
```

The student edits one or more canonical facts, returns to the same answer list,
and explicitly finishes the review. The workspace marks the affected documents
and requires regeneration. Financial statement cards expose their income,
expense, asset, liability, and schedule collections from the same list.

The implementation does not require a student to use the browser back button or
remember where a variable was first asked.

## Regeneration and invalidation

When a canonical fact changes, the workspace performs these steps.

1. Determine which generated documents use that fact.
2. Mark every selected dependent document as needing review or revision.
3. Freeze the regenerated PDF under a new revision and version.
4. Mark the prior generated snapshot as superseded.
5. Clear approval if the approved content changed.
6. Mark signed or notarized artifacts as potentially stale rather than deleting
   them.
7. Explain the impact to the student.
8. Require a deliberate regenerate/review decision.

A typo correction to a client name may affect many documents. A change to a
separation-agreement term may affect only that agreement and related findings.
Adapters define the dependency and invalidation scope.

The system preserves prior artifacts for audit and comparison unless the
retention policy requires deletion. A replacement upload does not destructively
overwrite the earlier file.

## Common received-file flows

### Existing document for reference

1. Student selects **Add received file**.
2. Student selects **Existing document for reference**.
3. Student identifies the document family and source.
4. The file is stored as an unverified reference artifact.
5. The student may confirm that a filing already exists or schedule preparation
   of an updated version.
6. The file does not enter a bundle automatically.

### Client-completed or annotated copy

1. Student uploads the file as `external_working_draft` or
   `client_annotated_reference`.
2. The workspace asks how the clinic should use the file.
3. Student updates the relevant canonical answers.
4. A new generated revision is created.
5. The generated revision follows ordinary supervisor review.

### Signed or notarized return

1. Student uploads the returned file and states what it is claimed to be.
2. An assigned supervisor verifies the document identity, expected execution
   marks, and claimed status.
3. After verification, the execution status advances.
4. A failed check leaves the upload unverified and does not advance execution.
5. Only a verified execution artifact may enter the relevant bundle.

### Filed or court-returned copy

1. Student uploads the file and records filing method and date.
2. For a court-returned copy, the student records acceptance, rejection, a need
   for follow-up, and any court or clerk note.
3. An assigned supervisor verifies the uploaded evidence.
4. Acceptance advances the filing state. Rejection or follow-up creates a
   revision blocker while preserving the returned copy in the records history.

## Artifact history

Each upload or generation records the following provenance data.

- stable artifact ID.
- document ID and purpose.
- revision/version.
- uploader or generator.
- timestamp.
- verification actor and timestamp.
- superseded artifact, if any.
- resulting status transition.
- a short non-confidential activity description.

File hashes may be recorded to detect accidental duplicate uploads. Hashes do
not replace access control or human verification.

## Bundle rule

An artifact enters a court-use or records bundle only when all of the following
conditions are true.

- the filing plan includes it.
- prerequisites are satisfied.
- the correct revision is selected.
- required review is approved.
- required execution checks are complete.
- an authorized team member deliberately includes it in that bundle.

Reference uploads are excluded by default.
