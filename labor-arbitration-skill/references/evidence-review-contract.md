# Human-gated evidence review contract v1.0

This contract records a local user's bounded evidence assessment, proof purposes, open gaps and generic strengthening actions. It never authenticates evidence, determines admissibility, weighs evidence, verifies relevance or supplies legal advice.

## Bound input

The build specification embeds one successful parser record, one or more active replay-valid fact candidates from that same parser record, a valid structured fact-analysis record, and the analysis predecessor when required. Every supplied candidate must be used by at least one proof purpose. Every purpose view must bind an exact supplied candidate snapshot.

The specification contains case-derived text, labels, dates, amounts and subject keys. It is D3 case data and must remain in the approved local workspace. It must never be committed, attached to an Issue/PR, sent to CI, logged, placed in telemetry or sent to an unapproved model endpoint.

## User assessment boundary

The user may self-declare:

- asserted source category;
- asserted completeness;
- asserted subject and time link, including an explicit mismatch;
- asserted original-byte preservation, transformation or alteration concern;
- known or unknown legality-risk flags;
- a proof-purpose proposition linked to exact structured views;
- another evidence-review ID as a possible corroborating record.

All fields remain `USER_*_UNAUTHENTICATED`. `NONE_DECLARED_UNVERIFIED` cannot coexist with another legality-risk flag. Corroborating IDs are unique, cannot self-reference and are not checked for external existence or evidentiary independence.

## Deterministic gaps and actions

The policy always keeps `AUTHENTICITY_UNVERIFIED` and `LEGALITY_REVIEW_REQUIRED` open. Unknown, partial, mismatched, transformed, altered, uncorroborated or risk-flagged user assessments create additional fixed gap codes.

Each gap maps to a versioned generic action such as preserving the full context, original/transformation chain, time metadata, subject identifiers, acquisition provenance, independent corroboration or independent legality review. Actions are `GENERIC_ACTION_NOT_LEGAL_ADVICE`; they never predict admissibility, weight, burden satisfaction or case success. Gaps and actions cannot be removed or hand-edited without invalidating the RFC 8785 record.

## Hard output boundary

Regardless of positive user assertions or a declared corroborating record:

- authenticity is `UNVERIFIED`;
- admissibility is `NOT_DETERMINED_REQUIRES_LEGAL_REVIEW`;
- evidence weight is `NOT_ASSESSED`;
- legality review is `PENDING_LEGAL_REVIEW`;
- output is `INTERNAL_ANALYSIS_ONLY`;
- submission readiness is false.

Offline record validation proves only structure, deterministic gaps/actions, proof-purpose bindings and record hashes. It cannot revalidate the external parser, candidate, analysis or corroborating records without the build specification, so upstream existence/currentness remains explicitly outside its verified scope.
