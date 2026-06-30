# Scopecat Architecture

Status: accepted architecture baseline

Scopecat is a local-first experiment workflow library. The core package owns
generic records, validation, planning, storage boundaries, and workflow
orchestration. Domain vocabulary and hardware policy stay in example packages,
future extensions, or private adapters.

The repository has no external compatibility contract. When a better model is
accepted, update code, tests, fixtures, and docs in the same pass instead of
keeping alias layers.

## Experiment Kernel

Every experiment lowers to one small planning kernel:

```text
points -> params -> state -> acquire
```

| Stage | Responsibility |
|---|---|
| `points` | Deterministic relation rows, one row per logical acquired point. |
| `params` | Point-local parameter patches evaluated against a parameter build snapshot. |
| `state` | Desired logical resource state derived from point rows and patched parameters. |
| `acquire` | Acquisition shape, shots, repetitions, dimensions, record mode, and estimated counts. |

Everything else is a boundary around that kernel: pulse compilation, hardware
execution, scheduling, storage validation, data access, analysis, candidate
config review, config activation, recovery, import, and domain-specific
compiler policy.

There is no durable `target` field. A target-like value is ordinary relation
data such as `qubit_id`, `readout.device_id`, `line_id`, `resource_id`, or
`sample_id`. Fixed targets, swept targets, selected target sets, and
simultaneous multi-target control all use the same relation model.

## Core Concepts

| Concept | Responsibility |
|---|---|
| `Quantity` | Numeric value plus unit, with explicit compatible conversions. |
| `RelationExpr` | Durable relation and scalar expression IR. |
| `Diagnostic` | Stable code, message, severity, and optional source location. |
| `ArtifactRef` | Content-addressed or storage-backed reference to large or external data. |
| `ParameterCatalog` | Scalar/table schemas, units, keys, constraints, lifecycle metadata, and validation policy. |
| `ParameterState` | Accepted scalar values and accepted table rows for future runs. |
| `ParameterBuildSnapshot` | Immutable resolved parameters, derived outputs, diagnostics, hashes, and provenance. |
| `ParameterPatch` | Scalar or table changes used for point-local views and candidate config review. |
| `ExperimentSpec` | Durable declarative recipe with `id`, `kind`, `points`, `params`, `state`, `acquire`, and optional `assets`. |
| `PlanSnapshot` | Durable aggregate with hashes, diagnostics, point previews, patch rows, desired state, acquisition shape, artifact refs, and provenance. |

`PlanSnapshot` should not embed a full per-point copy of every parameter table.
Store sampled previews or artifact-backed preview tables when users need to
inspect patched views at scale.

## Relation Expressions

Scopecat owns a small relation IR. It may use an execution engine such as
Polars internally later, but the durable contract is not Polars, pandas, Python
callbacks, or arbitrary string substitution.

Initial relation roots include `literal_rows`, `values`, `linspace`,
`range_values`, `grid`, `table`, and `parameter_table`.

Initial operations include `select`, `filter`, `join`, `cross`,
`with_columns`, `sort`, and `limit`.

Initial scalar terms include `col`, `outer`, `param`, `lit`, arithmetic,
comparison, boolean logic, conditionals, and selected pure functions such as
unit conversion and power conversion.

Variable-key parameter lookup is a join:

1. project keys from the current point row or repeated relation row;
2. join against the target parameter table;
3. require exactly one matching row unless the API explicitly requests many;
4. project the requested column.

This replaces dynamic dictionary paths, string substitution, and scan-specific
parameter maps.

## Boundary Ownership

Core owns generic records and validation:

- quantities, units, relation expressions, and diagnostics;
- parameter catalogs, states, derivations, build snapshots, patches, change
  sets, and candidate-review validation;
- experiment specs, planning, desired state, dry-run snapshots, acquisition
  plans, result contracts, and run manifests;
- generic storage references, artifact refs, events, analysis records,
  lower-level automation records, and boundary input/output schemas.

Domain packages own domain vocabulary and compilers:

- qubit, resonator, coupler, pulse, line, sample, and gate vocabulary;
- experiment templates and calibration recipes;
- sequence/pulse compiler IR;
- waveform routing and lazy waveform generation;
- hardware sweep/offload policies;
- classifier artifacts and readout schemas.

Boundary adapters own side effects and operational policy:

- imports from CSV, XLSX, JSON, registry, or private runner formats;
- native instrument execution and runner-adapter translation;
- resource leases, timing barriers, crash recovery, and resume point selection;
- hardware program grouping and mixed backend strategy;
- large artifact chunk assembly and artifact availability checks;
- analysis, promoted analysis steps, online analysis, early stop, and adaptive
  continuation;
- candidate config review, internal proposal finalization, quality acceptance
  policy, config activation, and parameter invalidation;
- multi-run calibration campaigns and monitor row materialization.

If a use case requires pseudo-resources such as `resource-scheduler`,
`campaign-orchestrator`, `resume.policy`, `stream.batch`, or
`classifier-gate`, model that as a boundary input around an ordinary
experiment. Do not add it to `ExperimentSpec.state`.

## Package Boundaries

| Package | Role |
|---|---|
| `scopecat.relations` | Relation expressions, scalar expressions, quantity/unit helpers, relation validators, and durable serialization. |
| `scopecat.parameters` | Catalog/state/build/patch/change-set models, derivation evaluation, validation, diffs, and candidate-review utilities. |
| `scopecat.experiments` | `ExperimentSpec`, authoring fragments, planner, dry-run previews, and plan snapshots. |
| `scopecat.results` | Result contracts, measurement schemas, row validation, retry summaries, artifact eligibility, and storage-facing records. |
| `scopecat.workflows` | Run lifecycle, data access, analysis persistence, candidate config review, comparison, campaign, resume, and scheduling. |
| `scopecat.importers` | Optional anti-corruption package for CSV, XLSX, JSON, registry, and private runner inputs. |

Example support packages live outside `packages/`. The current quantum demo
support package is `examples/quantum/support`, which owns domain-shaped
examples, virtual lab providers, reusable readout analysis, and quantum-like
templates for the runnable examples.

Core modules must not import demo support packages or quantum-domain modules.
Domain packages may depend on core plan records and core expressions when a
real package boundary is deliberately extracted.

## Design Notes

Use these focused documents for subsystem details:

- [Parameter system](parameter-system.md)
- [Native experiment kernel detail](native-experiment-definition-design.md)
- [Experiment workflow](experiment-workflow.md)
- [Storage workspace and manifest contract](storage-workspace-manifest-contract.md)
- [Measurement storage backends contract](measurement-storage-backends-contract.md)
- [PlanSnapshot preview storage contract](plan-snapshot-preview-storage-contract.md)
- [Relation execution and function registry contract](relation-execution-function-registry-contract.md)
- [Calibration state shape contract](calibration-state-shape-contract.md)
- [Diagnostics catalog contract](diagnostics-catalog-contract.md)
- [Domain package extraction contract](domain-package-extraction-contract.md)

New design work should update the smallest relevant contract document first,
then update this architecture note only after the decision becomes baseline.
