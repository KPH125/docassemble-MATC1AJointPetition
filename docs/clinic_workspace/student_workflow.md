# Student clinician workflow

> **Status: implemented and runtime-certified in an isolated environment.** The
> tasks and safety rules below describe current behavior.

## Start or resume work

After signing in, a student lands on the clinic caseload dashboard rather than
inside an arbitrary unfinished question.

A student with no matters sees a first-use empty state and one primary action:
**Create your first matter**. Review and closed filters use distinct empty
states after at least one matter exists. Returning to the dashboard performs a
fresh caseload query, so a newly created or updated matter appears without
depending on the original browser tab.

Students can perform the following actions.

- resume an assigned matter.
- create a matter.
- see work returned by a supervisor.
- see blocked documents and missing information.
- see upcoming execution or filing tasks.
- open closed matters in read-only mode.

## Create a matter

Matter creation collects the following information.

- a clinic-safe matter label.
- the case posture and intended task.
- which party or parties the clinic represents or assists.
- an optional internal due date.
- the documents to prepare now or later.

The creator is the initial owner. An owner, assigned supervisor, or clinic
administrator adds collaborators and supervisors by Docassemble user ID after
the matter exists.

The filing plan can change. Changing it reruns dependency checks and explains
the effect before adding or removing document work.

## Navigate and understand progress

The matter workspace owns one navigation rail across the parent and all
included document interviews. On a small screen, the same sections appear in a
dropdown. The sections are as follows.

- Matter setup
- Matter overview
- Questions and draft
- Review and revisions
- Signature and filing
- Bundles and closeout

The workspace progress summary distinguishes planned documents with a current
file, approved documents, and documents with a signed, notarized, or filed
copy. It measures work recorded in the workspace; it does not claim that a
court has completed the case. While the student is inside a document workflow,
the screen identifies the current matter and document and provides a **Return
to matter** action.

## Work on a document

Each document appears as a card with the following information.

- current status.
- assigned person.
- missing facts or dependencies.
- latest generated or received version.
- supervisor review state.
- signature, notarization, and filing state.
- the next recommended action.

Common actions include the following options.

- Answer questions
- Update answers
- Add received file
- Generate new draft
- Submit for review
- Respond to requested changes
- Record signed or notarized copy
- Add filed or court-returned copy
- Add to bundle

## When a client sends a file

The student opens the related document card and selects **Add received file**.
The student identifies whether it is a reference, annotated copy, signed copy,
notarized copy, filed copy, or replacement.

For a received working file, the student chooses one of three dispositions.
The student can keep it as a reference, use the exact file as the working
document, or update canonical answers and regenerate. The last option opens the
clinic-owned answer list for that document. The student does not search the
combined interview for the original field.

The received file remains available as a versioned artifact. It does not alter
answers or enter a court bundle until the student completes the applicable
review. Choosing **Update answers and regenerate** opens the relevant
document's labeled answer list.

## Correct and regenerate a document

1. Select **Review or update answers** on the document card.
2. Choose a labeled answer or collection from the clinic review screen.
3. Correct the canonical case facts and return to the same list.
4. Select **Done reviewing answers**.
5. Return to the document card and select **Regenerate draft**.
6. Review the affected-document state.
7. Resubmit any content whose prior approval is no longer valid.

The workspace preserves the prior version and explains why it was superseded.

## Request supervisor review

The student resolves required blockers and selects **Submit for review**. The
supervisor receives the document in their review queue and may take one of the
following actions.

- approve it.
- request changes with a document-specific comment.
- identify a missing dependency or client decision.

Requested changes return the document to the assigned student. Approval applies
to the reviewed revision, not every future regeneration.

## Record execution and filing

For a returned signed, notarized, or filed document, the student uploads the
artifact. An assigned supervisor completes the verification checklist. The
workspace then updates the execution or filing status and identifies the file.

An incomplete signature, missing notarization, clerk rejection, or stale version
creates a visible blocker and follow-up task.

## Prepare bundles

The workspace builds separate bundles for the following destinations.

- court use.
- student/client records.

The final review explains what is included, excluded, deferred, or blocked.
Reference uploads remain excluded unless a student deliberately selects an
eligible, verified artifact.

## Close the matter

Before closure, the student and supervisor review the following items.

- filing and execution state.
- unresolved items.
- intentionally deferred work.
- final records bundle.
- retention instructions.

Only an assigned supervisor or clinic administrator closes a matter. A
completed closure is rejected while a planned document remains unfinished.
Other closure reasons include withdrawal, transfer, and administrative closure.
Closed matters are read-only. Only a clinic administrator can reopen them.
