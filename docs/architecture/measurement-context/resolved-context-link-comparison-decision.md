# Resolved Context-Link Comparison Promotion Decision

## Status

Accepted narrow promotion.

## Decision

Promote the validated resolved context-link comparison candidate into a
route-local engineering prototype under `scopecat.measurement_context`.

The promoted surface is intentionally narrow:

- compare a current measurement record against a user-selected reference
  measurement record;
- compare actual resolved measurement-record context links, not prospective
  measurement intent selectors;
- report objective changed, same-observed, and missing optional-context
  findings;
- keep context records as family-owned summaries and reference-only links.

The accepted chain is:

```text
explicit current/reference measurement record pair
  -> user-selected reference mark
  -> resolved measurement-record context links
  -> local objective comparison findings
```

This promotion keeps resolved context-link comparison as a side-effect-free
review projection. It does not read primary measurement data, compare fit
quality, inspect context payloads, traverse relation graphs recursively, import
linked context, claim readiness, infer cause, control hardware, write
parameters, mutate setup bindings, sync environments, import code, execute
code, restore context, define GUI behavior, or define a shared context schema.

## Boundary

The promoted output is a local `review_summary` / local review projection. It
is not a portable/public/export artifact.

Repository fixtures remain repository-safe validation fixtures. Runtime
redaction is not added at this boundary because the promoted surface does not
produce portable handoff, package, or public documentation artifacts. The live
implementation still validates public-safe managed references and rejects
payload-comparison, intent-selector, required-validity, and unsupported
include-state expansions where the boundary owns those facts.

## Rationale

Selected-reference comparison can already compare explicit fixture context.
Resolved context-link comparison is a different authority: actual
measurement-record context links after run start. Promoting this narrow support
surface lets route owners compare recorded context without accepting a shared
relation graph, schema, payload diff engine, restore system, or cause-analysis
system.

## Engineering Coverage

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Resolved context-link comparison | Promoted into route-local engineering code with typed request/result objects and a raw-dictionary adapter only at the fixture/current-caller edge. | [`scopecat/measurement_context/README.md`](../../../scopecat/measurement_context/README.md), this decision |
| Selected-reference comparison consumption | This module provides resolved-link comparison findings that selected-reference review flows may consume later. It does not change the selected-reference module API. | [`scopecat/selected_reference/README.md`](../../../scopecat/selected_reference/README.md) |
| Measurement context-link construction | Promoted separately into route-local engineering code as explicit link summary construction. | [`context-link-construction-decision.md`](context-link-construction-decision.md) |
| Remaining measurement-context support families | Named run-start inputs, supporting evidence, artifact provenance/observation, post-run review, and context readiness remain implementation-candidate evidence. | [`../../discovery/synthesis/measurement-context-backlog.md`](../../discovery/synthesis/measurement-context-backlog.md) |

## Next Decision Gate

Do not continue by promoting the whole measurement-context backlog. Future work
should choose one explicit authority change:

- named run-start input-set construction;
- measurement-record context-link construction or storage integration;
- supporting evidence references and artifact provenance/observation;
- post-run review bundle composition;
- context readiness projection;
- selected-reference or prepared-run consumption of resolved-link findings;
- GUI or notebook presentation.

Each path needs its own non-claims before it can add payload reads, recursive
relations, context import, storage mutation, readiness/run-blocking decisions,
restore behavior, execution, or shared schemas.
