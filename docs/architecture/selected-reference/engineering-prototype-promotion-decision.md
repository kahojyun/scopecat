# Selected Reference Engineering Prototype Promotion Decision

## Status

Accepted narrow promotion.

## Decision

Promote the validated selected-reference comparison candidates into a
route-local engineering prototype under `scopecat.selected_reference`.

The promoted surface is intentionally narrow:

- basic context comparison over explicit current/reference measurement facts,
  user-selected reference marks, declared preview metadata, named input
  snapshots, selected context artifacts, and declared facts;
- recorded-code context comparison over recorded code context identity, code
  snapshot record identity, included file inventory, and declared context refs;
- local objective findings such as changed, missing, unverified, redacted,
  unlinked, same-observed, and not-compared scope.

The accepted chain is:

```text
explicit current/reference measurement pair
  -> user-selected reference mark
  -> declared comparison scope
  -> declared context facts
  -> local objective comparison findings
```

This promotion keeps selected-reference comparison as a side-effect-free review
projection. It does not inspect raw measurement payloads, compare fit quality,
inspect Git state, read source files, restore workspaces, resolve dependency
closure, execute code, prove physical setup truth, decide reference goodness,
infer cause, or define a shared context schema.

## Boundary

The promoted outputs are local `review_summary` / local review projections.
They are not portable/public/export artifacts.

Repository fixtures remain repository-safe validation fixtures. Runtime
redaction is not added at this boundary because the promoted surfaces do not
produce portable handoff, package, or public documentation artifacts. The live
implementation still validates public-safe managed references and redacted
display facts where the comparison boundary owns them.

## Rationale

Selected-reference comparison has a stable side-effect-free candidate boundary
with two useful dimensions: declared measurement context and recorded-code
context. Promoting those two surfaces lets downstream review flows consume
objective comparison findings without turning Scopecat into a user-judgment
engine, raw-data analysis system, Git diff tool, or execution/restoration
system.

## Engineering Coverage

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Selected-reference basic context comparison | Promoted into route-local engineering code with typed request/result objects and raw-dictionary adapters only at the fixture/current-caller edge. | [`scopecat/selected_reference/README.md`](../../../scopecat/selected_reference/README.md), this decision |
| Selected-reference recorded-code context comparison | Promoted as declared recorded-code context comparison only. It compares context IDs, snapshot record identities, included file inventory, source-observation tokens, and declared refs without Git, source reads, restore, dependency, or execution claims. | [`scopecat/selected_reference/README.md`](../../../scopecat/selected_reference/README.md), this decision |
| Resolved measurement-record context-link comparison | Promoted separately as measurement-context support. It is not part of this module because its authority is actual measurement-record context links rather than the current selected-reference fixture shapes. | [`../measurement-context/resolved-context-link-comparison-decision.md`](../measurement-context/resolved-context-link-comparison-decision.md), [`../../../scopecat/measurement_context/README.md`](../../../scopecat/measurement_context/README.md) |

## Next Decision Gate

Do not continue by promoting the whole selected-reference route. Future work
should choose one explicit authority change:

- GUI or notebook review presentation over comparison findings;
- quick preview/overlay consumption over compatible declared preview metadata;
- raw-data or fit-quality comparison;
- setup truth or hardware-state comparison;
- richer experiment-code comparison using managed versions or editable
  observations.

Each path needs its own non-claims before it can add payload reads, fit
judgment, setup truth, restore behavior, execution, or shared schemas.
