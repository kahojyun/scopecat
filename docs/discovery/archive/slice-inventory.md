# Discovery Slice Inventory

## Status

Compact historical index.

The detailed discovery slice body corpus was removed from the active
documentation tree. Git history preserves the full validation plans, validation
results, implementation-plan notes, and fixture-shaped summaries.

Use current architecture, product, engineering, brownfield, and route owner
documents for active meaning. Do not treat former slice files as current
architecture, roadmap, API, schema, or implementation guidance.

## Current Owners

| Current Owner | Use For |
| --- | --- |
| [`../../architecture/README.md`](../../architecture/README.md) | Brownfield-guided domain model, context map, and transition architecture. |
| [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md) | Current use-case and workflow validation state. |
| [`../../engineering/implementation-register.md`](../../engineering/implementation-register.md) | Live implementation owners. |
| [`../../engineering/prototype-boundaries/README.md`](../../engineering/prototype-boundaries/README.md) | Accepted engineering prototype boundaries. |
| [`../../product/target-journeys.md`](../../product/target-journeys.md) | Target journeys and use cases. |
| [`../../brownfield/README.md`](../../brownfield/README.md) | Current-state, migration, transition, and risk posture. |

## Former Slice Groups

| Former Path | Historical Coverage | Default Classification | Current Replacement |
| --- | --- | --- | --- |
| `docs/discovery/slices/measurement-records/` | Legacy/adapted run recording, source observation, normalized primary data, selected export, running inspection, storage transition, and repeated review projections. | Historical validation; accepted boundary evidence where already promoted. | Measurement Records module docs, prototype-boundary notes, workflow validation map, architecture domain model. |
| `docs/discovery/slices/measurement-records/handoff/` | Handoff package writer/open/read/view-model/visual/receiving/integrity/import candidate slices and route pressure fixtures. | Historical validation; some accepted boundary evidence summarized in current handoff docs. | Handoff module docs, handoff prototype-boundary notes, JNY-001 validation rows, architecture transition map. |
| `docs/discovery/slices/parameter-state/` | Adapter-authored parameter intake, storage/read views, selection, prepared-run review projections, compatibility-output candidates, and review gates. | Historical validation; accepted boundary evidence where promoted. | Parameter State module docs, parameter-state prototype-boundary note, workflow validation map. |
| `docs/discovery/slices/environment-operation/` | Modern manifest preflight, `uv sync` intent/result, and environment operation review bundles. | Historical validation; accepted operation evidence where promoted. | Environment Operation module docs and prototype-boundary note. |
| `docs/discovery/slices/experiment-code/` | Code recording, context inclusion, managed code version, materialization, editable-folder observation, environment comparison, and rerun-preparation candidates. | Product-candidate and historical validation evidence. | Architecture domain/context maps, experiment-code discovery route, workflow validation candidates. |
| `docs/discovery/slices/measurement-context/` | Context links, supporting evidence/artifact references, post-run review bundles, context readiness, and selected-reference context comparisons. | Mostly concept-only or slice-to-slice glue unless current owners cite a narrower behavior. | Architecture domain model and context map; workflow validation candidates. |
| `docs/discovery/slices/calibration/` | Calibration continuation, fit recovery, action recording, proposed/accepted write links, timeline, findings, and review-state projections. | Historical validation and product-candidate evidence; over-fragmented review-state slices should be summarized, not restored. | Architecture transition map, calibration route decision, workflow validation candidate. |
| `docs/discovery/slices/selected-reference/` | Selected-reference comparison validation. | Product-candidate evidence. | Architecture domain model and workflow validation candidate. |
| `docs/discovery/slices/setup-binding/` | Setup-binding snapshot and validation evidence. | Product-candidate evidence. | Architecture domain/context maps and setup-binding route notes. |
| `docs/discovery/slices/support/` | Contract primitives and filesystem mutation helpers. | Historical technical-risk evidence; promote only through explicit owner decision. | Engineering prototype-boundary notes or live module docs when applicable. |

## Deleted Body Policy

The removed slice bodies should not be restored wholesale. If a future task
needs a deleted slice, recover only the narrow fact needed from Git history and
move that fact into the current owner.

Before reusing a former slice concept, classify it with
[`../../architecture/transition-architecture.md`](../../architecture/transition-architecture.md):

- current architecture evidence;
- accepted boundary evidence;
- risk evidence;
- historical validation;
- concept-only experiment;
- slice-to-slice glue;
- misleading direction.

Historical `receipt` outputs need special care. Reclassify them as operation
results, durable audit records, review summaries, manifests, or slice-to-slice
glue before using them in current architecture.
