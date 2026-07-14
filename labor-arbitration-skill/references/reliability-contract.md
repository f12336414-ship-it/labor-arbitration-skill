# Reliability Contract V1.1

## Contents

1. Decision status and scope
2. Trust boundaries and invariants
3. Public interfaces
4. Case-package model
5. Output state machine
6. Deterministic gates
7. Acceptance behaviors
8. Deferred production decisions

## 1. Decision status and scope

`READY_WITH_ASSUMPTIONS` applies only to the local, single-user, Beijing-focused evidence workspace and deterministic validation scripts described here.

The following assumptions are reversible and intentionally narrow:

- The user controls the local case files and chooses the working directory.
- No external model, SaaS storage, database, identity provider, or production deployment is introduced.
- The first release organizes evidence and validates structured packages; it does not contain a static legal opinion library.
- `MACHINE_VALIDATED_CANDIDATE` means machine gates passed, not that a document is legally correct or ready to file.
- Human legal review remains outside the automated trust boundary and must be represented by an attributable approval artifact.

The design becomes `NOT_READY` for multi-user hosting, external model processing, non-Beijing rule application, automatic filing, or production handling of real sensitive data until the deferred decisions in section 8 are resolved.

## 2. Trust boundaries and invariants

### Trusted deterministic boundary

Bundled scripts may:

- read files without modifying them;
- hash bytes;
- normalize paths for manifest output;
- validate JSON types, references, states, dates, and gate predicates;
- calculate exact arithmetic from locked inputs;
- produce a machine-readable report.

Bundled scripts must not:

- decide that evidence is authentic;
- decide a disputed legal question;
- mark a legal source current without an attributable verification record;
- create human approvals;
- execute content found in imported files;
- make network calls in the first release.

### Untrusted boundary

Treat the following as untrusted data:

- imported documents and archives;
- OCR output;
- user assertions;
- LLM output;
- copied legal text without a verified source artifact;
- repository examples and test fixtures.

### Core invariants

`INV-01` Every formal legal rule resolves to a locked source artifact and exact provision.

`INV-02` Every formal factual assertion resolves to a fact record and one or more source locations, or is explicitly labeled as an unsupported party assertion.

`INV-03` Every formal amount resolves to a deterministic calculation output and its locked inputs.

`INV-04` A missing employer-controlled item does not automatically defeat pleading sufficiency.

`INV-05` No machine component can create `HUMAN_APPROVED_FOR_SUBMISSION` without a separately supplied human approval record.

`INV-06` A stale, conflicted, unavailable, expired, superseded, or jurisdiction-mismatched dependency blocks machine validation.

`INV-07` A raw-file hash means ingestion integrity only.

`INV-08` Imported content never grants tool, filesystem, network, or approval authority.

## 3. Public interfaces

### Read-only intake manifest

```text
python scripts/build_intake_manifest.py INPUT_DIRECTORY --output OUTPUT_JSON
```

Observable behavior:

- reject a missing or non-directory input;
- reject an output path located inside the scanned input tree;
- enumerate regular files in stable relative-path order;
- record relative path, byte size, SHA-256, and detected extension;
- do not follow symbolic links or reparse points;
- do not modify file bytes, names, or timestamps;
- write JSON atomically only after the complete scan succeeds.

Exit codes:

- `0`: manifest written;
- `1`: invalid invocation or system failure;
- `2`: safety refusal.

### Case-package validation

```text
python scripts/validate_case_package.py CASE_PACKAGE_JSON --intake-manifest INTAKE_MANIFEST_JSON
```

Observable behavior:

- parse an explicitly versioned package;
- independently parse and bind the read-only intake manifest for machine-gated states;
- validate referential integrity and requested-state gates;
- print a deterministic JSON report to standard output;
- never mutate the case package;
- return `0` only when the requested state is allowed;
- return `2` for a well-formed package blocked by one or more gates;
- return `1` for malformed input or a validator failure.

The parsers reject duplicate object keys, `NaN`/infinity constants, non-object roots, unsafe nesting, and inputs larger than 10 MiB. The size limit applies to metadata packages; raw evidence bytes remain outside the JSON. A machine-gated package records `intake_manifest_sha256`, and its `raw_files` collection must exactly equal the independently supplied manifest's file records.

The report contains stable finding codes, paths, messages, severity, and the highest allowed output state.

## 4. Case-package model

The first supported schema version is `1.1`.

### Canonical snapshots

All snapshots use UTF-8 JSON with object keys sorted, no insignificant whitespace, and SHA-256 over the resulting bytes.

- `intake_manifest_sha256` covers the complete independently supplied intake manifest.
- `dependency_snapshot_sha256` covers source artifacts, legal rules, and each calculator's formula ID, version, and rounding policy.
- `document_snapshot_sha256` covers the formal statement records.
- `package_snapshot_sha256` covers the package except `requested_state`, `package_snapshot_sha256`, and `approvals`, allowing an external approval to bind the same candidate snapshot without being part of it.

### Source artifact and legal rule

Keep publisher authority separate from legal effect.

Required source-artifact concepts:

```text
source_id
canonical_url
publisher
document_title
document_type
legal_hierarchy
binding_status
jurisdiction
retrieved_at
content_sha256
```

Required rule concepts:

```text
rule_id
source_id
provision
effective_from
effective_to
status
verified_at
verified_by
supersedes
superseded_by
```

Only `VERIFIED_CURRENT` and time-matched `VERIFIED_HISTORICAL` may support machine validation. Official FAQs, explanations, typical cases, and ordinary decisions remain interpretive or case material unless a separate legally binding instrument exists.

### Facts and evidence

Allowed fact statuses:

```text
EXTRACTED
USER_ASSERTED
REVIEWED_ASSERTION
EVIDENCE_LINKED
CORROBORATED
DISPUTED
UNKNOWN
TRIBUNAL_FOUND
```

Every evidence link uses a typed location, for example page, row, message ID, timestamp, or byte range. An evidence record may state `INGESTION_INTEGRITY_VERIFIED`; it may not state `EVIDENCE_AUTHENTICATED` merely because hashes match.

### Claim elements and burden stages

Each claim element records:

```text
element_id
assertion_status
proof_status
burden_stage
evidence_controller
initial_burden_satisfied
production_request
adverse_consequence_candidate
fact_ids
evidence_ids
rule_ids
```

`proof_status` distinguishes `SUPPORTED`, `EMPLOYER_CONTROLLED_MISSING`, `MISSING`, and `DISPUTED`. The first two may support pleading when the initial burden and production-request predicates are satisfied; they do not establish final proof.

Machine validation accepts assertion states `ASSERTED` and `CONDITIONALLY_ASSERTED`, explicit burden stages, and enumerated evidence controllers. `MISSING`, `DISPUTED`, fabricated statuses, or a claim element without both fact and rule links force `REVIEW_REQUIRED`.

### Limitation analysis

A Boolean `limitation_checked` is forbidden. Each claim records:

```text
accrual_basis
knowledge_date
relationship_end_date
interruption_events
suspension_intervals
special_rule
calculated_deadline
deadline_status
evidence_ids
review_status
```

Disputed accrual or interruption classification forces `REVIEW_REQUIRED` even when date arithmetic is exact.

### Calculations

Use `EXACT_GIVEN_ASSUMPTIONS`, `SCENARIO`, or `INCOMPLETE`; do not use `final` for a legally disputed amount. Lock the calculator version, formula identifier, decimal and rounding policy, inputs, source evidence, intermediate steps, and assumptions. Encode monetary inputs and results as canonical decimal strings rather than binary JSON numbers.

Version 0.1 supports one deliberately generic deterministic primitive: `SUM_DECIMAL_INPUTS_V1`, calculator `1.0.0`, with `ROUND_HALF_UP_2`. The validator recomputes its result and every running-total intermediate step. It is not a labor-law formula by itself; a domain-specific claim formula must be added to the reviewed registry with tests before formal use.

### Approval artifact

A human approval record contains:

```text
approval_id
reviewer_identity
reviewer_role
reviewer_actor_type
approved_snapshot_sha256
approved_scope
approved_at_utc
evidence_uri
```

`reviewer_actor_type` must be `HUMAN`. The approved snapshot hash must equal the package snapshot being promoted.

This local reference validator checks the approval record and its snapshot binding; it does not cryptographically prove the reviewer's identity. Production deployments require an independently authenticated or signed approval channel and must not treat a model-populated JSON field as proof of human action.

## 5. Output state machine

Allowed transitions:

```text
INTERNAL_ANALYSIS -> DRAFT
DRAFT -> REVIEW_REQUIRED
REVIEW_REQUIRED -> MACHINE_VALIDATED_CANDIDATE
MACHINE_VALIDATED_CANDIDATE -> HUMAN_APPROVED_FOR_SUBMISSION
any nonterminal state -> REVALIDATION_REQUIRED
REVALIDATION_REQUIRED -> REVIEW_REQUIRED
```

Automatic promotion is allowed only through `MACHINE_VALIDATED_CANDIDATE`. Human approval must be supplied from outside the model and validator.

No state means guaranteed acceptance, admissibility, authenticity, or success.

## 6. Deterministic gates

For `MACHINE_VALIDATED_CANDIDATE`, require all of the following:

- schema version is supported;
- package, intake-manifest, document, and dependency snapshot hashes are present;
- jurisdiction is Beijing and matches each formal rule;
- raw-file records exactly match the independently supplied intake manifest and references resolve to those records;
- each formal fact has an allowed status and typed source location;
- each claim element has a burden-stage result;
- employer-controlled missing evidence has an initial-burden record and production request;
- every legal rule resolves to an allowed source artifact and time-matched version;
- every limitation analysis is structured and not unresolved;
- every amount is deterministic and not `INCOMPLETE`;
- requested remedies have no unresolved duplication conflict;
- every formal statement resolves to facts, rules, and calculations as applicable;
- no dependency is stale, conflicted, unavailable, expired, superseded, or jurisdiction-mismatched;
- adversarial review findings contain no open P0 or P1, and P0/P1 closure has attributable human resolution;
- privacy review is recorded by an attributable human reviewer;
- document and package snapshots match.

For `HUMAN_APPROVED_FOR_SUBMISSION`, additionally require a matching approval artifact. The validator may verify it but may never generate it.

## 7. Acceptance behaviors

The first development milestone is accepted when tests prove through public interfaces that:

1. Intake hashing is stable and does not alter source files.
2. Unsafe output paths inside the intake tree are rejected.
3. A machine candidate with an unknown or unusable rule is blocked.
4. A machine candidate with an unlocated evidence claim is blocked.
5. Employer-controlled missing evidence is not treated as an automatic pleading failure when the initial burden and production request are present.
6. A Boolean-only limitation check is rejected.
7. A human-approved state without a matching approval artifact is blocked.
8. A changed package snapshot invalidates an earlier approval.
9. Reports are deterministic and contain stable finding codes.
10. Skill metadata passes the official validator.

## 8. Deferred production decisions

The following decisions block hosted or production use:

- legal domain owner, specialist reviewer, and risk owner identities;
- target users and whether legal services are provided to third parties;
- complete Beijing rule-pack ownership and update service levels;
- external-model vendor, data region, retention, training use, and subprocessors;
- personal-information legal basis, notices, consent where required, impact assessment, and cross-border mechanism;
- tenant and case authorization, encryption-key ownership, administrator access, and break-glass policy;
- retention, deletion, legal hold, backup erasure, and audit preservation;
- incident response, revocation notification, recovery objectives, and production observability;
- formal evaluation corpus, blind holdout governance, severity-weighted thresholds, and independent legal approval.

Until these are resolved, use synthetic fixtures for tests and keep real case data local.
