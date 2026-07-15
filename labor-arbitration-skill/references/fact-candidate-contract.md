# Fact candidate and replayable anchor contract v1.0

This contract governs local pre-analysis assertions derived from bounded parser output. It does not create a legal fact, authenticate evidence, identify a reviewer, or approve submission.

## States are provenance labels, not truth ranks

| State | Exact meaning | Forbidden inference |
| --- | --- | --- |
| `EXTRACTED` | One exact parser anchor copied by the machine | A human checked it; it is true or legally relevant |
| `USER_ANNOTATED` | A self-declared, unauthenticated local user wrote or confirmed an assertion tied to one or more anchors | The user identity or assertion is verified |
| `ADJUDICATED` | A self-declared, unauthenticated user classified one exact anchor as a passage from an adjudicative document | The document is authentic/effective, the passage is a tribunal finding, or the fact is established |

`ADJUDICATED` is retained as the roadmap's required label, but its machine-readable context is permanently `UNVERIFIED` in v1.0. No state maps automatically to `TRIBUNAL_FOUND`, a claim element, a calculation input, or a formal document.

## Replay and revision rules

Every candidate binds the parser record snapshot, workspace, raw object content hash, anchor ID, kind, coordinate and exact anchor text hash. Validation requires the exact parser record. A derived record also requires its exact immediate predecessor.

Allowed transitions are:

1. create `EXTRACTED` from exactly one unchanged anchor;
2. derive `USER_ANNOTATED` from an active `EXTRACTED` record;
3. derive `ADJUDICATED` from an active `EXTRACTED` record and one unchanged passage;
4. invalidate any active candidate by creating a new immutable revision.

Edits in place, state promotion without the predecessor, transition from one human label to another, timestamp rollback, missing anchors and source/parse changes fail closed. The predecessor remains an auditable record; invalidation never deletes history.

## Identity, privacy and downstream use

Actor labels are self-declared display labels, not accounts, signatures or professional credentials. They are case data and remain local under the data-governance policy. Production identity, RBAC and signed audit remain externally blocked.

Successful validation proves only structural replay and revision integrity. It never establishes evidence authenticity, fact truth, legal relevance, adjudicative document authenticity/effect or submission readiness. Human-labelled candidates must undergo independent evidence and legal review before any downstream use.

## Current anchor coverage

Text lines, CSV/XLSX cells, DOCX paragraphs, email headers/body lines and archive entries replay against parser records. PDF/image pages, OCR boxes, chat-message identities and media timepoints remain unsupported, so roadmap item P1-06 is `FOUNDATION`, not `DONE`.
