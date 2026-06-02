# Experiment Code Route Consolidation

## Status

Discovery consolidation note, not an ADR.

This note harvests the current experiment-code validation work into one
route-level view. It does not accept final managed workspace storage, a Git
replacement, branch/merge/sync semantics, code loading, import, execution,
workflow/DAG behavior, generated-artifact regeneration, environment
restoration, hardware control, shared run-context schema, or GUI contract.

## Route Shape

The validated chain of adjacent experiment-code slice responsibilities is
**record, promote, materialize, observe, prepare**:

```text
recorded code context
  -> code snapshot record
  -> managed code version
  -> workspace materialization intent
  -> approved workspace materialization
  -> editable-folder observation
  -> prepared run context
```

Reference-based rerun preparation is a later convenience branch over prepared
run context and selected-reference links. It does not change the code route
authority: selected reference context can seed a proposed manual rerun, but it
does not prove reproducibility, cause, or readiness.

This chain is not a mandatory workflow for every measurement. It records the
order in which current slices have earned stronger local claims.

The broader experiment-start workflow is documented in
[`run-preparation-workflow-boundary-validation-result.md`](../../slices/experiment-code/run-preparation-workflow-boundary-validation-result.md).
That boundary separates legacy/passive context recording from a future
template/prepared route, and places prepared-run context after adapters or
preparation helpers have already produced normalized context references.

In the wider route model, measurement records remain the user-facing evidence
or selection anchor. Experiment code is one linked context family for those
measurements, runs, or steps: it records what code root, entrypoint, managed
version, materialized workspace, or editable observation was associated with
the work. Prepared run context is the current local composition surface that
joins selected code/workspace context with parameter, setup, station,
measurement intent, declared environment context, and separately validated
environment review findings for manual run preparation.

## Current Track Map

| Track | Current slices | Earned responsibility |
| --- | --- | --- |
| Recording | Experiment code recording | Represent one external code root, entrypoint, explicit include policy, capture-state posture, and code snapshot record without scanning Git or executing code. |
| Managed record | Managed code version | Promote a code snapshot record into a managed-version record with aligned inventory and integrity hints, without storage backend or restore semantics. |
| Declared comparison | Comparable code surface | Compare explicit recorded/managed code facts and capture-state limits without reading source, semantic diff, Git diagnostics, import, or execution. |
| Materialization planning | Workspace materialization intent | Plan workspace-relative destinations and review findings from declared facts without filesystem inspection or writes. |
| Approved materialization | Workspace materialization | Write declared managed content into a caller workspace after approval, with no-overwrite behavior and no Git/environment/execution authority. |
| Workspace observation | Editable-folder observation | Read a selected editable workspace against a managed code version, report drift and extras, and keep semantic diff/Git/execution out of scope. |
| Run-context composition | Prepared run context | Compose selected managed code/workspace observation with parameter/setup/station/measurement context and optional unavailable environment context or locally required missing-context findings for manual run preparation. |
| Rerun convenience | Reference-based rerun preparation | Seed a proposed manual rerun context from selected-reference linked context without accepting reproducibility, correction, or execution authority. |

## Boundary Map

| Surface | Boundary posture | Responsibility |
| --- | --- | --- |
| Recorded code context | Local record summary | Captures explicit code context and capture states for a run or step; not a managed workspace or executable checkout. |
| Code snapshot record | Local managed-candidate record | Names future managed scope and capture posture; not final storage, restore, or execution. |
| Managed code version | Local managed-version record | Carries identity, inventory, and integrity hints; not a selected loaded workspace by itself. |
| Materialization intent | Local review plan | Plans destinations and collisions; does not inspect or mutate the filesystem. |
| Materialized workspace | Approved local filesystem mutation | Creates editable files under caller roots; not a Git checkout, environment restore, or run target by itself. |
| Editable-folder observation | Local read-only observation | Reports drift from selected managed version; not semantic source diff, Git status, or readiness. |
| Prepared run context | Local `review_summary` composition | Groups selected code/workspace and other run-start context; does not import, execute, or decide run readiness. |
| Handoff/package references | Future reference-only package entries unless separately validated | May reference code context, managed version, workspace/materialization, or prepared run context records; does not own code packaging or restore. |

## Scopecat Owns

These concepts have enough repeated pressure to carry forward inside this
route:

- code snapshot records tied to run or step context;
- explicit include policy and capture-state vocabulary, including
  content-captured, reference-only, missing, redacted, and excluded surfaces;
- managed code version identity, inventory alignment, and integrity hints;
- side-effect-free materialization plans before approved writes;
- no-overwrite workspace materialization under caller-provided roots;
- read-only editable-folder observation against selected managed-version
  inventory;
- prepared run context as the current composition point for selected code,
  workspace observation, parameter/setup/station context, measurement intent,
  optional unavailable declared environment context, and locally required
  missing-context findings.

## Not Yet Earned

Keep these outside the accepted route until a separate slice explicitly earns
authority:

- final managed workspace storage or content-addressed backend;
- Git replacement behavior, branch/merge/conflict/sync semantics, or Git
  diagnostics as product output;
- default record-all folder tracking;
- semantic source diff, generated-artifact dependency inference, or build
  pipeline regeneration;
- loading, importing, or executing selected code;
- notebook execution;
- workflow/DAG nodes or component-level code versioning;
- environment restoration or dependency sync;
- hardware control or managed runner behavior;
- GUI language for save, restore, compare, or use-version actions.

## Still Candidate-Local

Keep these concepts local until another implementation task would otherwise
duplicate the same behavior and boundary rules:

- fixture-specific code roles and display wording;
- materialization path policy beyond the current caller-root/no-overwrite
  behavior;
- editable-folder ignored-directory guardrails;
- comparison finding wording beyond declared-fact comparison;
- prepared-run context selected-record shape;
- any shared helper extraction between code, environment, and handoff routes.

## Existing Composition

The current route already has composition pressure through
`prepared_run_context`. That slice validates selected managed code version,
editable workspace observation, parameter state, setup binding, station
registry, measurement intent, optional unavailable declared environment
context, and locally required missing-context findings in one manual
run-preparation summary.

Do not add a separate "code readiness bundle" merely to restate managed
version, materialization, and editable-folder observation. A new composition
slice is justified only if a real consumer needs one review surface that is not
already covered by prepared run context or reference-based rerun preparation.

## Engineering Coverage

Freezing the validation results does not mean every discovery candidate became
a live engineering surface. Use this matrix when deciding whether to update an
old validation result, the architecture note, or the module README.

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Experiment-code recording, managed code version, workspace materialization intent, approved workspace materialization, editable-folder observation, reference-based rerun preparation | Implementation candidate only. The previous promoted module was withdrawn because candidate-summary parity was doing too much architectural work. | Historical implementation candidates and validation results. |
| Prepared-run context over selected code/workspace context | Implementation candidate only. Future prepared-run work should promote a workflow-shaped boundary rather than reuse summary parity as the owner. | Historical prepared-run candidates and validation results. |
| Declared environment inventory, environment comparison, environment file observation, environment review, and manager-operation slices | Owned by environment-operation or historical discovery docs; not promoted as experiment-code APIs. | [`environment-operation/README.md`](../environment-operation/README.md), [`environment-operation.md`](../../../architecture/boundaries/environment-operation.md) |
| Comparable code surface and selected-reference comparison | Retained as discovery evidence and route pressure. No semantic diff, Git diagnostics, or shared comparison API is promoted here. | Historical validation results and future narrower decisions if reopened. |

## Cross-Route Relationship

Current cross-route coupling should stay reference-based:

- measurement records or selected references anchor why a code context is
  selected, but they do not make the measurement route own code recording,
  materialization, comparison, or execution contracts;
- prepared run context can reference declared environment records, but code
  selection does not own environment sync or runtime readiness;
- environment-operation summaries can reference prepared run context and
  declared environment, but they do not load or execute selected code;
- handoff package work may eventually carry references to code context,
  managed code version, or prepared run context records;
- package import/export does not currently restore code workspaces, sync
  environments, or claim runnable readiness;
- measurement and calibration routes can attach code context references without
  accepting a shared run-context or workflow/DAG schema.

## Future Boundaries

These are separate product authority questions:

1. **Code loading/execution**: validate import/load/execute authority,
   interpreter context, cwd, arguments, output capture, timeout/cancel, and
   failure classification separately from recording and materialization.
2. **Managed workspace storage**: validate final storage, content-addressing,
   archive/Git-backed implementation, and freshness semantics only when a
   concrete backend question appears.
3. **Semantic diff or Git diagnostics**: validate only for a workflow that
   needs stronger source interpretation than declared digest/path comparison.
4. **Workflow/DAG support**: validate only after stable recurring routines need
   component-level code versions, inputs, outputs, and compatibility review.
5. **Experiment context package projection**: validate package references or
   safe artifacts separately before packaging code or claiming restore.

## Test And Fixture Posture

Future tests should prefer route behavior over restating every low-level
candidate contract:

- keep focused fixtures for new authority cases such as managed-version
  inventory comparison, capture-state edge cases, or additional editable-folder
  observations;
- keep one negative test per new boundary vocabulary or path/identity category;
- prefer route-level fixtures only when they pressure prepared-run or rerun
  user workflows;
- avoid adding composition solely to duplicate prepared run context;
- keep repository fixtures small and repository-safe; local review summaries
  are not automatically portable/public/export artifacts.

## Recommended Next Work

The current route is ready to pause broad code-route expansion. The next work
should depend on the product question being answered:

1. **If handoff continuity is the priority**, validate reference-only
   experiment context package projection before packaging code artifacts.
2. **If execution is the priority**, validate code loading/execution as a
   separate authority boundary after environment/runtime questions are explicit.
3. **If managed storage is the priority**, validate one storage backend or
   content-addressed/archive/Git-backed decision with real write/read pressure.
4. **If comparison is the priority**, add a managed-version inventory or
   capture-state edge fixture before designing semantic diff.

Do not add another experiment-code slice merely to restate recording,
managed-version identity, materialization planning, editable-folder
observation, or prepared-run context. Those are now route-level conclusions
unless a new user workflow challenges them.
