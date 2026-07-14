# ADR-0002: Schema 1.3 integrity bindings

Status: Accepted
Date: 2026-07-14

## Context

The v0.2 scanner used sequence-based raw IDs, performed one complete tree enumeration, and hashed JSON with Python-specific `json.dumps` settings. The case snapshot excluded `requested_state`, the statement-only hash was named as though it covered rendered documents, and the intake manifest did not state whether generator or provenance fields were authenticated.

Those properties were internally deterministic but insufficient for stable cross-tool handoff. Expanding them without a schema break would silently change hash meaning.

## Decision

v0.3 uses case-package and intake-manifest schema 1.3 only.

- `raw_id = "RAW-" + SHA256(UTF8(relative_path) || 0x00 || content_sha256_bytes)`.
- The scanner completes an initial walk, hashes every file through a stable descriptor, rechecks each path, then completes a second full walk and compares the complete observed tree.
- JSON hashes use RFC 8785. Non-I-JSON values fail closed.
- `statement_snapshot_sha256` replaces the misleading `document_snapshot_sha256` name.
- `package_snapshot_sha256` includes `requested_state` and excludes only itself, `state_request_sha256`, and the always-empty `approvals` collection.
- `state_request_sha256` binds the requested state to the package, intake, dependency, and statement snapshots without claiming actor authentication.
- Manifest generator, clock, filesystem, content-type, and path observations are explicitly `UNATTESTED`; user provenance is `NOT_PROVIDED`.
- Local manifest self-hashing detects mutation but is not a signature. GitHub Tag artifacts receive a separate build-provenance attestation.

## Consequences

Schema 1.2 packages and manifests must be rescanned and rebuilt; changing only the version is invalid. Existing raw IDs change once during migration. Future unrelated file insertion no longer renumbers retained records, while path or content changes deliberately create a new ID.

The second tree walk narrows but cannot eliminate filesystem races. Successful manifests still do not represent an atomic filesystem snapshot and do not authenticate bytes, operators, timestamps, or generator origin.
