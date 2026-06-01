# Measurement Context Link Construction Promotion Decision

## Status

Accepted narrow promotion.

## Decision

Promote the validated measurement context-link candidate into a route-local
engineering prototype under `scopecat.measurement_context`.

The promoted surface is intentionally narrow:

- summarize explicit measurement-record context links for one or more
  measurement records;
- allow records with zero context links;
- keep linked context records as family-owned, reference-only summaries;
- surface missing optional context as review findings;
- keep measurement-record primary-data validity independent from context.

The accepted chain is:

```text
explicit measurement records
  -> explicit family-owned context record summaries
  -> explicit resolved or missing optional context links
  -> local context-link review summary
```

This promotion keeps context-link construction side-effect-free. It does not
read primary data, inspect context payloads, recursively traverse relation
graphs, import linked context, store or mutate context links, claim readiness,
control hardware, write parameters, mutate setup bindings, sync environments,
import code, execute code, restore context, define GUI behavior, or define a
shared context schema.

## Boundary

The promoted output is local review data. It is not a portable/public/export
artifact.

Repository fixtures remain repository-safe validation fixtures. Runtime
redaction is not added at this boundary because the promoted surface does not
produce portable handoff, package, or public documentation artifacts. The live
implementation validates public-safe managed identifiers and rejects policy
expansion, required-for-record-validity context, unsupported families,
unsupported include states, wrong-family links, missing linked context, and
unreasoned unavailable optional context.

## Rationale

Resolved context-link comparison is already promoted, but it compares
measurement records after links exist. This decision promotes the smaller
producer-side review surface for explicit context links without accepting
storage, relation graph behavior, payload reads, restore, execution, or shared
schema work.

## Engineering Coverage

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Measurement context link | Promoted into route-local engineering code with typed request/result objects and a raw-dictionary adapter only at the fixture/current-caller edge. | [`scopecat/measurement_context/README.md`](../../../scopecat/measurement_context/README.md), this decision |
| Resolved context-link comparison | Remains the side-effect-free comparison consumer over actual resolved links. | [`resolved-context-link-comparison-decision.md`](resolved-context-link-comparison-decision.md) |
| Supporting evidence references | Promoted separately into route-local engineering code as reference-only review evidence. | [`supporting-evidence-reference-decision.md`](supporting-evidence-reference-decision.md) |
| Remaining measurement-context support families | Named run-start inputs, artifact provenance/observation, post-run review, and context readiness remain implementation-candidate evidence. | [`../../discovery/synthesis/measurement-context-backlog.md`](../../discovery/synthesis/measurement-context-backlog.md) |

## Next Decision Gate

Do not continue by promoting the whole measurement-context backlog. Future work
should choose one explicit authority change:

- named run-start input-set construction;
- context-link storage or mutation behavior;
- supporting artifact provenance/observation;
- post-run review bundle composition;
- context readiness projection;
- selected-reference or prepared-run consumption of context-link findings;
- GUI or notebook presentation.

Each path needs its own non-claims before it can add payload reads, recursive
relations, context import, storage mutation, readiness/run-blocking decisions,
restore behavior, execution, or shared schemas.
