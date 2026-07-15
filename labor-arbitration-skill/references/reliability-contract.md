# Reliability Contract V1.3

## 1. Purpose and guarantee level

This contract governs v0.3.0 of the local reference-integrity core. The technical identifier remains `labor-arbitration-skill` for compatibility.

The highest automated state is `REFERENCE_INTEGRITY_VALIDATED`. It means only that the requested v1.3 technical checks passed for a locked snapshot. It never means:

- a fact is true;
- evidence is authentic or semantically supportive;
- a source is current, authoritative, complete, correctly quoted, or applicable;
- limitation, jurisdiction, employer identity, claim elements, remedies, or amounts are legally correct;
- privacy review or risk acceptance occurred;
- a human identity, role, signature, or approval was authenticated;
- a document is complete, admissible, submission-ready, or likely to succeed.

The mandatory next state is `PENDING_LEGAL_REVIEW`, outside this project's trust boundary. The machine-readable capability registry is [capabilities.json](capabilities.json).

## 2. Supported scope

- Case materials remain in local filesystem processing only. A separate public-source client may make one controlled HTTPS request to an explicit registered URL.
- Single process and single user; no account or tenant model.
- Python 3.10 or later.
- Case-package and intake-manifest schema `1.3` only.
- Packages declared as `CN / Beijing` only. This is a narrow input scope, not a jurisdiction determination or Beijing rule-pack guarantee.
- Synthetic test data only in the repository and CI.

Hosted processing, external model transfer, multi-user access, automatic filing, authenticated approval, real legal conclusions, and any non-Beijing rule application are `NOT_READY`.

## 3. Trust boundaries

Untrusted inputs include filenames, file contents, document metadata, prompts embedded in materials, user-entered records, model output, URLs, publisher labels, hashes supplied in JSON, dates, statuses, reviewer names, and approval-like artifacts.

Trusted implementation scope is limited to:

- bounded traversal and hashing of stable opened regular files;
- local content-addressed case-object creation and hash replay;
- replayable structural-anchor fact candidates, direct-predecessor revision binding, and immutable invalidation records;
- exact user-structured date/amount/subject conflict detection and registered-view dependency invalidation;
- human-gated evidence assessment, proof-purpose binding, deterministic gap identification, and generic strengthening actions;
- bounded official-source HTTPS transport evidence and response-body freezing;
- structural legal-version graphs, exact UTF-8 text diffs, technical freshness bindings, and historical interval candidates;
- RFC 8785 JSON canonicalization and hashing;
- identifier and cross-reference checks;
- manifest equality and snapshot binding;
- the specified decimal addition and rounding primitive;
- fail-closed state decisions and deterministic reports.

No model or local JSON field receives legal, evidentiary, privacy, risk, identity, approval, or submission authority.

## 4. Invariants

`INV-01` Imported content is data, never executable instruction.

`INV-02` A manifest describes bytes observed during ingestion and never authenticates evidence.

`INV-03` A reference link proves only that the target ID exists in the locked package.

`INV-04` A source-host allowlist match is only a candidate-origin filter.

`INV-05` Rules remain `UNVERIFIED_CANDIDATE`; verified/current/historical/applicable states are unavailable.

`INV-06` Limitation remains `UNVERIFIED`, `calculated_deadline` remains `null`, and legal review remains pending.

`INV-07` The generic sum may report `ARITHMETIC_RECOMPUTED` only; it never reports a professional or final legal amount.

`INV-08` Fact and proof states cannot claim tribunal findings, corroboration, semantic support, or authenticated review.

`INV-09` JSON names, actor types, roles, timestamps, URIs, or hashes never create a human approval, privacy approval, or P0/P1 risk resolution.

`INV-10` A content, requested-state, or dependency change invalidates its RFC 8785 binding and requires revalidation.

`INV-11` Schema 1.2 and older schemas, plus the states `MACHINE_VALIDATED_CANDIDATE` and `HUMAN_APPROVED_FOR_SUBMISSION`, are rejected; downgrade is not a compatibility path.

`INV-12` A zero exit code authorizes only the requested technical state. `legal_review_required` remains `true`.

`INV-13` A workspace, frozen source, version graph, diff, freshness check, historical selection, or official-case record proves only its explicitly reported technical scope.

`INV-14` Missing, unavailable, stale, or changed legal-source freshness permits `DRAFT` only; unchanged response bytes still do not prove legal currentness.

`INV-15` Public case access never removes privacy, reuse-policy, rate-limit, or complete-case evaluation requirements.

## 5. Intake manifest

The scanner:

- traverses with `os.scandir` without following links;
- rejects symbolic links, Windows reparse points and junctions, nested mount points, special files, network roots, unreadable entries, and output inside the input tree;
- uses one opened descriptor for pre-read metadata, hashing, size, and post-read metadata;
- compares the final path identity and metadata before publishing;
- performs a second complete tree walk and rejects any added, removed, renamed, or observation-signature-changed file;
- refuses a file that changes during observation;
- derives each `raw_id` from the UTF-8 relative path and observed content SHA-256, so unrelated insertions do not renumber existing files;
- records byte-prefix media-type hints, extension mismatch flags, duplicate-content groups, and hardlink candidates without parsing content;
- writes the completed manifest atomically and enforces POSIX mode `0600`; on Windows it records that inherited directory ACLs were not verified;
- never executes or parses file contents.

Default bounds are:

| Limit | Default |
| --- | ---: |
| Files | 10,000 |
| Single file | 100 MiB |
| Total bytes | 1 GiB |
| Directory depth | 20 |
| Scan deadline | 60 seconds |

Successful records use `INGESTION_BYTES_OBSERVED` and `SYSTEM_OBSERVED_UNATTESTED`. User provenance remains `NOT_PROVIDED`. The manifest binds configured limits, two scan timestamps from an unattested system clock, exact file-count/byte summary, generator/runtime metadata, output-security status, derived relationships, and an RFC 8785 payload self-hash. None of those fields authenticates the scanner build or operator. Cancellation by the caller may stop the process; no partial manifest is published.

The scanner cannot create a filesystem-wide atomic snapshot. Files may change after a successful scan; consumers must retain and compare the locked manifest, rescan on change, and protect storage with external controls.

## 6. Canonical snapshots

Canonical JSON uses RFC 8785 (JCS), including its I-JSON input constraints, ECMAScript primitive serialization, UTF-16 object-property ordering, UTF-8 output, and no insignificant whitespace.

Cross-language consumers must pass the published [RFC 8785 vectors](rfc8785-vectors.json) before exchanging hashes.

- `manifest_payload_sha256` covers the v1.3 intake manifest excluding that self-hash field. It detects mutation but does not authenticate origin.
- `intake_manifest_sha256` covers the complete supplied v1.3 intake manifest, including its self-hash.
- `dependency_snapshot_sha256` covers source candidates, unverified rules, and calculator identifiers/versions/rounding policies.
- `statement_snapshot_sha256` covers formal statement records only. It deliberately does not claim rendered-document integrity.
- `package_snapshot_sha256` covers the package, including `requested_state`, except `state_request_sha256`, `package_snapshot_sha256`, and `approvals`.
- `state_request_sha256` binds the requested technical state to the package, intake, dependency, and statement snapshots. It does not authenticate the actor or authorize a transition.

The `approvals` collection must be empty. It is excluded only to make legacy tampering visible through the explicit approval rejection and to preserve deterministic migration behavior; it never grants authority.

## 7. Source candidates

The validator requires HTTPS, no credentials, no non-default port, no fragment, a declared publisher code, a small exact host allowlist, and `content_hash_status=DECLARED_UNVERIFIED`. Host mismatch and unsupported hash status are separate error codes. Retrieval timestamps must be RFC 3339 UTC; rule and limitation inputs must be real ISO calendar dates, and a rule end date cannot precede its start date.

Current candidate mappings are:

| Publisher code | Allowed host candidates |
| --- | --- |
| `NATIONAL_LAWS_REGULATIONS_DATABASE` | `flk.npc.gov.cn` |
| `STATE_COUNCIL` | `www.gov.cn` |
| `SUPREME_PEOPLES_COURT` | `www.court.gov.cn` |
| `MOHRSS` | `www.mohrss.gov.cn` |
| `BEIJING_GOVERNMENT` | `www.beijing.gov.cn` |
| `BEIJING_HRSS` | `rsj.beijing.gov.cn`, `fuwu.rsj.beijing.gov.cn` |

The case-package validator does not perform HTTP requests. A separate single-document fetcher follows bounded same-publisher redirects, freezes exact response-body bytes, records selected response/TLS metadata, and replays body hashes offline. Candidate version graphs, complete bounded UTF-8 text diffs, freshness observations, and event-date interval selections are separately available. They do not retain raw HTTP framing, attest the clock, prove automated-access authorization or publisher authorship, verify relationship legal correctness, cover every amending instrument, determine legal currentness or applicability, or provide scheduled monitoring. Therefore no rule may be marked verified. Future source states and their proof requirements are defined in [the trust-state model](../../docs/trust-state-machine.md); current case/review schemas still accept none of those future legal states.

Official public-case collection uses a separate shared rate-limit ledger and `OFFICIAL_CASE` registry purpose. It accepts one explicit URL, freezes the response, and emits privacy-gated classification metadata with redistribution blocked. It is not a crawler and does not extract holdings, remove personal information, establish reuse permission, or create a complete-case corpus.

## 8. Evidence and facts

Evidence requires a raw-file ID and a typed non-empty location. The validator checks that IDs exist and that raw records equal the bound manifest.

Allowed fact states are `USER_ASSERTED`, `EVIDENCE_LINKED`, `DISPUTED`, and `UNKNOWN`. `EVIDENCE_LINKED` means reference existence only.

The project implements bounded inert extraction candidates for UTF-8 text, CSV, DOCX, XLSX and plain-text email plus non-recursive ZIP entry inspection. A separate fact-candidate ledger replays supported structural anchors and records three provenance labels: `EXTRACTED` is one exact machine-copied anchor; `USER_ANNOTATED` is a self-declared unauthenticated local user's statement; `ADJUDICATED` is only a self-declared unauthenticated classification of one exact passage from a purported adjudicative document. The last label does not authenticate the document, its legal effect, a tribunal finding, or the asserted fact. Derived records bind their direct predecessor and invalidation creates a new revision rather than deleting history. No fact candidate automatically enters a case fact, claim, calculation, or formal document.

For conflict analysis, a local user may separately provide canonical dates, non-negative CNY values or opaque subject keys bound to active fact-candidate snapshots. Engine `STRUCTURED_FACT_CONFLICTS/1.0.0` reports every exact unequal pair, semantic-kind mismatch, reversed employment boundary and termination outside a declared employment boundary. It never chooses a value or resolves a conflict. Its direct-predecessor ledger invalidates registered downstream analysis when a view or candidate snapshot is added, removed or changed, including a candidate snapshot change with the same value.

The project does not implement PDF parsing, OCR, image/chat/audio/video transcription, attachment recursion, operating-system parser sandboxing, page or timestamp existence checks, semantic value extraction, evidence ranking, authenticity analysis, semantic support scoring, proof-standard analysis, authenticated human identity, professional confirmation, or discovery of unregistered downstream copies. Current structural anchor replay therefore completes P1-07 but leaves P1-06 at `FOUNDATION`; deterministic conflicts complete P1-08, while end-to-end downstream dependency enforcement leaves P1-10 at `FOUNDATION`.

A separate evidence-review ledger validates same-parser active candidates and selected structured views before recording a user's source, completeness, subject, time, original-byte/integrity and legality-risk assertions. Proof-purpose propositions remain user assertions. Open gaps deterministically generate generic preservation, provenance, context, identifier, time, transformation-chain, corroboration or independent-review actions. A fake corroborating review ID cannot close authenticity or legality gaps and is never verified for existence or independence. Authenticity remains `UNVERIFIED`, admissibility requires legal review, evidence weight is not assessed and output stays internal-only.

## 9. Claims, limitation, and conflicts

Claim elements may record IDs and declared workflow fields. `initial_burden_status` must remain `UNVERIFIED`. The project has no authoritative claim-element catalog or burden engine.

Each claim carries a limitation data object, but it is data capture only:

- `calculated_deadline=null`;
- `deadline_status=UNVERIFIED`;
- `review_status=PENDING_LEGAL_REVIEW`.

Legacy case-package conflict records, if present, must remain `PENDING_LEGAL_REVIEW`. The separate structured-fact ledger emits only `PENDING_HUMAN_REVIEW` comparison conflicts with null auto-selection and resolution fields. Evidence review records bind proof purposes but cannot claim semantic relevance, corroboration, admissibility, proof strength or burden satisfaction. None of these mechanisms resolves a conflict. The project has no remedy compatibility, inclusion, offset, alternative-claim, or duplicate-period matrix.

## 10. Arithmetic

The only calculator is:

- formula `SUM_DECIMAL_INPUTS_V1`;
- calculator version `1.0.0`;
- rounding `ROUND_HALF_UP_2`;
- decimal-string inputs/results;
- status `ARITHMETIC_RECOMPUTED`.

It recomputes running totals and the final sum. It does not select a wage base, period, work-year fraction, cap, multiplier, remedy, tax treatment, paid-amount deduction, or claim relationship.

## 11. States and report contract

Supported package states are:

- `INTERNAL_ANALYSIS`;
- `DRAFT`;
- `REVIEW_REQUIRED`;
- `REFERENCE_INTEGRITY_VALIDATED`;
- `REVALIDATION_REQUIRED`.

For a successful reference-integrity request, the report returns:

- `allowed=true`;
- `allowed_scope=REQUESTED_TECHNICAL_STATE_ONLY`;
- `highest_allowed_state=REFERENCE_INTEGRITY_VALIDATED`;
- `legal_review_required=true`;
- `next_required_state=PENDING_LEGAL_REVIEW`;
- an explicit `validation_scope.verified` list;
- an explicit `validation_scope.not_verified` list.

Exit `2` means the parsed package is blocked. Exit `1` means an input is unreadable, malformed, unsafe, or over the parser limit.

## 12. Production gates not met

Production legal use remains blocked until independent owners approve and verify at least:

- authoritative, versioned Beijing rule content and an update/freeze service;
- per-claim limitation rules and legally reviewed test vectors;
- versioned professional calculators and remedy-conflict rules;
- evidence extraction, anchors, semantic/contradiction review, and human confirmation;
- jurisdiction, arbitration body, and employer identity verification;
- authenticated accounts, RBAC, separation of duties, signatures, immutable audit, retention, deletion, backup, and recovery;
- privacy/legal basis and vendor/transfer controls for any hosted or model processing;
- a governed, desensitized real-case evaluation corpus with severity-weighted acceptance thresholds;
- independent legal-domain and risk-owner release approval.
