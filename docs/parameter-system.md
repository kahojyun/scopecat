# Parameter System

Status: target design

Scopecat parameters are accepted configuration state and deterministic
planning inputs. They are not live device state, spreadsheet state, registry
trees, private runner dictionaries, analysis scratch values, or derived-view
mutation targets.

## Goals

- Represent scalar and table parameters with consistent schema, units,
  constraints, provenance, and validation.
- Keep accepted configuration separate from experiment-time patches, point
  local overrides, analysis outputs, and reviewed candidate changes.
- Let experiment sweeps and candidate configs reuse the same patch concepts.
- Make derived views deterministic, reproducible, hashable, and diagnosable
  without turning them into independent sources of truth.
- Keep hardware vocabulary and private lab formats outside core.
- Support explicit scopes and override provenance without hidden shadowing.

## Non-Goals

- Do not put pandas, openpyxl, xlwings, Polars, LabRAD, or private file readers
  in core parameter records.
- Do not make Excel, JSON settings folders, registry trees, or runner
  dictionaries durable Scopecat parameter formats.
- Do not let analysis, instruments, adapters, or notebooks mutate accepted
  parameter state silently.
- Do not encode qubit, resonator, coupler, pulse, or lab-specific vocabulary
  in core schemas.
- Do not persist full per-point parameter table copies unless a concrete
  artifact or review workflow requires them.

## Source Of Truth

`ConfigProfileSnapshot` is the authoritative input for planning. Parameter state is
one part of that snapshot.

Accepted state changes through explicit activation:

```text
accepted ConfigProfileSnapshot
  + reviewed ConfigPatch / ParameterChangeSet
  -> new accepted ConfigProfileSnapshot
```

Derived planning views are deterministic projections:

```text
ConfigProfileSnapshot + explicit inputs -> DerivedConfigView
```

A view may be materialized, cached, hashed, displayed, diffed, or referenced by
an `ExperimentSpec`, but it is not where accepted changes are written.

## Concepts

| Concept | Responsibility |
| --- | --- |
| `ParameterCatalog` | Defines scalar and table schemas, units, constraints, keys, lifecycle metadata, and validation policy. |
| `ParameterState` | Stores accepted scalar values and table rows inside a config snapshot, with deterministic content hashes. |
| `ConfigProfileSnapshot` | Immutable accepted planning input containing parameter state plus topology, routing, environment, and registry metadata. |
| `DerivedConfigView` | Deterministic projection such as planning parameters, topology view, backend compile view, review view, or analysis feature view. |
| `ParameterPatch` | Scalar or table change used for experiment-time patched views, point-local sweeps, and candidate resolution. |
| `ParameterChangeSet` | Candidate accepted-state patch set with source, reason, confidence, expected values, diagnostics, and provenance. |
| `ConfigPatch` | Broader candidate patch that may include non-parameter config sections when those sections become accepted config. |
| `EntityRef` | Typed reference to config-owned entities such as devices, channels, resources, samples, or topology nodes. |

`ExperimentSpec` consumes these concepts after compilation. It does not own
accepted configuration state.

## Catalog

`ParameterCatalog` is schema and validation policy. It should define:

- scalar ids, table ids, and column schemas;
- units and compatible conversions;
- primary keys and uniqueness requirements;
- required fields and defaults when appropriate;
- safety bounds and lifecycle metadata;
- owner, status, description, and review policy;
- schema versioning and diagnostic locations.

Resource mapping belongs in config or parameter tables, not as hidden catalog
behavior. Domain packages may define domain-specific catalogs outside core.

## State

`ParameterState` stores accepted scalar values and accepted table rows with
provenance and content hashes. It is immutable within a run.

Accepted state is not live hardware state. Readbacks are records. Desired
state is an experiment/runtime construct. Candidate values are patches until
activated.

## Derived Views

The architecture should allow multiple derived views without making them
parallel truth sources:

```text
PlanningParameterView
CalibrationReviewView
TopologyView
BackendCompileView
AnalysisFeatureView
QuantumCalibrationView
```

Views must declare inputs, compiler id/version, diagnostics, content hash, and
provenance when persisted. They can be recomputed from config and explicit
inputs.

Promote a view to a persisted first-class artifact only when users need to
review, visualize, diff, reuse, or cache it independently.

## Patches, Sweeps, And Overrides

`ParameterPatch` is used in three places:

- point-local experiment patches evaluated against point rows;
- run-request overrides with provenance;
- candidate config changes produced by analysis or adapters.

Patch operations include scalar replacement and table row insert/update/delete.
Every patch is validated against catalog schema, units, bounds, key
cardinality, and expected current values when relevant.

A run-time `parameter_sweep` is syntax for:

```text
point column
  + point-local ParameterPatch
```

For example, sweeping `readout.power` creates a point axis and a patch that
sets `readout.power` from that column. The compiler decides whether the sweep
participates in `point_uid`, checks shape and safety policy, and records
override provenance.

## Scope And Override Order

Scopes must be explicit. Future workflows may need:

```text
global config
sample/chip config
device/entity view
experiment override
run override
point-local patch
backend compile view
```

The system must record precedence, source, reason, expected old value when
available, and diagnostics. Hidden Python globals, notebook variables, or
registry writes are not valid override mechanisms.

## Candidate Configs

Analysis creates evidence and candidate patches. Candidate resolution is a
system step:

```text
analysis outputs
  -> ParameterChangeSet / ConfigPatch
  -> candidate ConfigProfileSnapshot
  -> validation, diff, preview
  -> follow-up run
  -> review / activation
```

Candidate objects do not mutate accepted config. Activation writes a new
accepted config snapshot and preserves lineage to source run, analysis
artifacts, change set, review decision, follow-up runs, and comparisons.

## Imports

Importers are one-way anti-corruption tools. CSV, XLSX, JSON, registry trees,
and private runner inputs should be parsed outside core and converted into
typed Scopecat config, parameter, or artifact records with diagnostics.

Core should not preserve private field names, local paths, registry layout, or
spreadsheet conventions as public API.

## Validation Expectations

Parameter validation should report stable diagnostics for:

- unknown scalar or table ids;
- missing required columns;
- duplicate primary keys;
- wrong value kind;
- unsupported or incompatible units;
- safety-bound violations;
- unknown derivation or view inputs;
- ambiguous variable-key lookup;
- unknown entity refs;
- invalid scope or override precedence;
- stale candidate expected values;
- invalid table patch operations.

Tests should assert durable records and diagnostic codes rather than private
helper placement.
