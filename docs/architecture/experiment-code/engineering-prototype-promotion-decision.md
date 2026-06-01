# Experiment-Code Engineering Prototype Promotion Decision

## Status

Accepted narrow promotion.

## Decision

Promote the validated experiment-code discovery candidates into a route-local
engineering prototype under `scopecat.experiment_code`.

The promoted surface is intentionally narrow:

- experiment-code recording and code snapshot summaries;
- managed code version summaries;
- workspace materialization intent summaries;
- approved no-overwrite workspace materialization;
- editable-folder observation;
- reference-based manual rerun preparation.

The accepted chain is:

```text
recorded code context
  -> code snapshot record
  -> managed code version
  -> workspace materialization intent
  -> approved workspace materialization
  -> editable-folder observation
  -> reference-based manual rerun preparation
```

The prototype keeps the discovery route boundary: record, promote,
materialize, observe, prepare. It does not extract shared core models and does
not introduce final managed storage, restore, Git replacement behavior,
semantic source diff, environment sync, code import, code execution,
hardware control, workflow/DAG behavior, or GUI contracts.

## Boundary

The promoted outputs are local `review_summary` / local review projections.
They are not portable/public/export artifacts.

Repository fixtures remain repository-safe validation fixtures. Runtime
redaction is not added at this boundary because the promoted surfaces do not
produce portable handoff or public documentation artifacts.

## Rationale

The discovery route already has adjacent validated slices for code context,
managed code versions, materialization planning, approved materialization,
editable observation, prepared-run context, and reference-based rerun
preparation. Keeping these behaviors route-local avoids duplicating the same
boundary rules in later callers while still preserving the explicit deferral
of shared context models and execution/storage authority.

## Engineering Coverage

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Experiment-code recording, managed code version, workspace materialization intent, approved workspace materialization, editable-folder observation, reference-based rerun preparation | Promoted into route-local engineering code with typed request/result objects and raw-dictionary adapters only at the fixture/current-caller edge. The live boundary belongs to the module and architecture docs; implementation candidates are historical evidence. | [`scopecat/experiment_code/README.md`](../../../scopecat/experiment_code/README.md), this decision |
| Prepared-run context over selected code/workspace context | Already promoted under the prepared-run route rather than duplicated in experiment-code. | [`../prepared-run/engineering-prototype-promotion-decision.md`](../prepared-run/engineering-prototype-promotion-decision.md) |
| Declared environment inventory, environment comparison, environment file observation, environment review, and manager-operation slices | Owned by environment-operation or historical discovery docs; not promoted as experiment-code APIs. | [`../environment-operation/engineering-prototype-promotion-decision.md`](../environment-operation/engineering-prototype-promotion-decision.md), discovery route docs |
| Comparable code surface and selected-reference comparison | Retained as discovery evidence and route pressure. No semantic diff, Git diagnostics, or shared comparison API is promoted here. | Historical validation results and future narrower decisions if reopened. |

Further work should stay driven by a concrete new authority question:
execution, managed storage, semantic diff, workflow/DAG support, or package
projection.
