# Structured fact conflicts and dependency invalidation contract v1.0

This contract converts replay-valid fact candidates into user-supplied canonical comparison values and emits deterministic unresolved conflicts. It is a local analysis aid, not semantic extraction, evidence authentication, fact finding or legal review.

## Input boundary

The build input embeds each fact-candidate record, its exact parser record and any direct fact-candidate predecessor. The builder first runs the published candidate/anchor validators. Invalidated candidates, broken parser bindings and missing predecessors are refused.

For each active candidate, a local user supplies:

- a stable `view_key` for dependency comparison;
- a `dimension_key` identifying the field being compared;
- exactly one canonical value: `YYYY-MM-DD`, non-negative CNY with two decimals, or an opaque uppercase subject key;
- an optional date timeline role: employment start, employment end or termination;
- a self-declared actor label.

These values are always `USER_STRUCTURED_UNAUTHENTICATED`. The system does not extract them from prose, authenticate the actor, match a subject key to a legal entity or establish the value's truth. Input specifications contain case-derived records and must remain in the approved local case workspace; they must never enter the repository, CI, Issue, PR, logs or telemetry.

## Conflict policy

Engine `STRUCTURED_FACT_CONFLICTS/1.0.0` uses exact canonical-string comparison and emits every unequal pair. It reports:

- semantic-kind mismatch for the same dimension;
- differing dates, CNY amounts or subject keys for the same dimension;
- employment start later than employment end;
- termination before a start or after an end.

Every conflict remains `PENDING_HUMAN_REVIEW`; `auto_selected_view_id` and `resolution` are always null. The engine never ranks evidence, silently overwrites a value, merges subjects or resolves a conflict.

The engine refuses more than 10,000 conflict records instead of truncating them. The operator may split the comparison into explicit dimensions or case phases, but must not drop a source merely to pass the limit.

## Dependency invalidation

Views are sorted by stable key and bind the fact-candidate ID, candidate snapshot, parse ID, parser snapshot, structured value, actor self-declaration and engine version through RFC 8785 hashes.

The first record creates `BASELINE_CURRENT`. A derived record requires its exact direct predecessor. Added, removed or changed view keys—including a candidate snapshot change with the same structured value—produce `INVALIDATED_BY_FACT_CHANGE`, enumerate the exact changed keys and require downstream revalidation. Unchanged views produce `CURRENT`.

This ledger knows only downstream work explicitly bound to its upstream snapshot. It cannot discover or invalidate unregistered files, copied text, external tools or hidden caches. Therefore P1-10 remains `FOUNDATION` until claims, calculations and documents all require this binding.

## Output boundary

Output permission is permanently `INTERNAL_ANALYSIS_ONLY`. Successful validation proves deterministic conflict generation, direct-predecessor invalidation and record integrity only. It never proves fact truth, evidence authenticity, identity, legal relevance, downstream completeness, approval or submission readiness.
