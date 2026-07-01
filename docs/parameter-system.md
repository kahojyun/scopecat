# Parameter System

Status: accepted subsystem detail

Scopecat parameters are accepted configuration state and deterministic planning
inputs. They are not live device state, spreadsheet state, registry trees, or
private runner dictionaries.

## Goals

- Represent sparse scalar parameters and row-oriented table parameters with
  consistent validation and provenance.
- Keep accepted state separate from experiment-time patches and reviewed
  candidate configuration changes.
- Use one relation-expression IR for table derivations, point construction,
  variable-key lookup, and repeated desired-state bindings.
- Make derived parameters deterministic and reproducible.
- Keep hardware vocabulary and private lab file formats outside core.
- Make parameter updates reviewable through the same patch model used by
  experiment-time overrides.

## Non-Goals

- Do not put pandas, openpyxl, xlwings, Polars, LabRAD, or private file readers
  in core.
- Do not make Excel, JSON settings folders, or registry trees durable Scopecat
  parameter formats.
- Do not let analysis, runner adapters, or instruments mutate
  active parameter state silently.
- Do not encode qubit, coupler, resonator, pulse, or lab-specific vocabulary
  in core models.
- Do not persist full per-point parameter table copies unless a concrete
  artifact requires it.

## Concepts

| Concept | Responsibility |
|---|---|
| `ParameterCatalog` | Defines scalar and table schemas, units, constraints, keys, lifecycle metadata, and validation policy. |
| `ParameterState` | Stores accepted scalar values and accepted table rows with provenance and content hashes. |
| `RelationExpr` | Durable table/column expression IR used by parameter derivations and experiment planning. |
| `ParameterDerivationSet` | Named deterministic expressions evaluated from accepted state. |
| `ParameterBuildSnapshot` | Freezes accepted state plus derived outputs, diagnostics, source hashes, and build metadata. |
| `ParameterPatch` | Describes scalar or table changes for experiment-time patched views and candidate config review. |
| `ParameterChangeSet` | Reviewable accepted-state candidate patch set with source, reason, expected values, and conflicts. |

`ExperimentSpec` consumes these concepts but is not part of the parameter
system. It owns point construction, parameter patches local to a run, desired
state, and acquisition.

## Catalog

`ParameterCatalog` is schema and validation policy. It should not contain
hardware routing decisions unless they are descriptive metadata.

Core catalog responsibilities:

- column type and unit validation;
- primary-key uniqueness;
- required fields;
- safety bounds;
- lifecycle metadata such as owner, status, and description;
- schema versioning and diagnostics.

Resource mapping belongs in parameter tables or system configuration, not in
the catalog schema itself.

## State

`ParameterState` is accepted source configuration for future runs. It stores:

- scalar values;
- table rows;
- source provenance;
- content hashes;
- update timestamps or revision identifiers when available.

Accepted state changes only through explicit candidate review and activation.
Experiment-time parameter patches create patched planning views; they do not
mutate accepted state.

## Build Snapshots

`ParameterBuildSnapshot` freezes the parameter view used for planning. It
contains accepted inputs, evaluated derivations, diagnostics, source hashes, and
provenance.

Planning consumes build snapshots, not raw config maps. This gives dry runs,
native runs, analysis, comparison, and structured overviews a stable record of
the parameter inputs used for each run.

## Patches And Candidate Review

`ParameterPatch` is used in two places:

- point-local experiment patches evaluated against point rows;
- reviewed candidate config changes produced by analysis or adapters.

Patch operations include scalar replacement and table row insert/update/delete.
Every patch is validated against the catalog and, where relevant, against the
expected accepted value to prevent stale writes.

`ParameterChangeSet` groups candidate accepted-state patches with source,
reason, diagnostics, and expected values. Activation writes a new accepted
state snapshot and preserves enough provenance to compare baseline and
candidate runs.

## Imports

Importers are one-way translation tools. CSV, XLSX, JSON, registry, and private
runner inputs should be parsed outside core and converted into typed Scopecat
models with diagnostics. Core should not preserve private field names or source
layout conventions as public API.

## Validation Expectations

Parameter validation should report stable diagnostics for:

- unknown scalar or table ids;
- missing required columns;
- duplicate primary keys;
- wrong value kind;
- unsupported or incompatible unit;
- safety-bound violations;
- unknown derivation inputs;
- ambiguous variable-key lookup;
- stale candidate expected values;
- invalid table patch operations.

Tests should assert durable records and diagnostic codes, not private helper
placement.
