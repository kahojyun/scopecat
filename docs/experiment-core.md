# Scopecat Experiment Core

Status: active design notes

These notes describe the experiment core currently being designed. They are
not a contract for internal schemas, record names, storage layout, diagnostic
codes, or Python APIs. During the redesign, breaking changes are expected when
they make the model simpler.

## Shape

The structured experiment path is:

```text
ExperimentModule + ExperimentTemplate + RunRequest + ConfigProfileSnapshot
  -> ExperimentSpec
  -> ExperimentPlan
  -> DeviceProgram
  -> InstrumentRuntime
  -> InstrumentGroup / Instrument
```

The core idea is to separate authoring intent, operator input, accepted
configuration, planning output, and runtime side effects.

`ExperimentModule` is reusable experiment library code. It can provide point
variables, defaults, helpers, state fragments, record fragments, program
assets, and pure code islands.

`ExperimentTemplate` is a runnable entrypoint. It exposes inputs and calls
module-level components. Templates should stay thin enough that repeated logic
can move back into modules.

`RunRequest` is the user's request for one run or segment. It records template
inputs, config source, operator metadata, run overrides, point axes, parameter
sweeps, seeds, extra records, execution flags, and segment lineage. It should
not contain materialized point tables, device routing, dataset layouts,
analysis decisions, or runtime order.

`ConfigProfileSnapshot` is the accepted configuration input for planning. It
may include parameter state, topology, routing, environment, and registry
metadata. It is not live device state and should not be mutated by instruments,
analysis, notebooks, or legacy registries during a run.

`ExperimentSpec` is the closed input for a structured run segment. Reusable
intent lives in modules/templates, operator input lives in `RunRequest`, and
accepted configuration lives in `ConfigProfileSnapshot`. The spec binds those
inputs into a concrete segment before side effects.

`ExperimentPlan` is the planner output for the current implementation. It may
materialize point rows, point-local patches, desired logical state, output
records, artifact refs, program refs, diagnostics, and compiler metadata. Its
shape may change aggressively while the core settles.

`DeviceProgram` is the runtime-facing command plan. It is built from the plan,
program artifacts, routing, instrument-group capabilities, and runtime policy.

## Experiment Model

The working calculation graph is:

```text
point_source / points
  -> params
  -> state
  -> records
  -> outputs
```

`point_source / points` describes the logical point space for a segment.
Small runs may materialize points directly. Larger, streaming, or adaptive
runs may keep a point source description plus an append-only decision log.

`params` are point-local configuration patches derived from point rows, run
overrides, and accepted config. A parameter sweep is syntax for a point column
plus a patch evaluated for each point.

`state` is desired logical resource or instrument-group state. Controls such
as integration time, readout length, average count, demod frequency, trigger
delay, and backend program selection belong here or in config-derived views,
not in a parallel acquisition-control system.

`records` are declarations for values or artifacts the run should produce.
Sources may include instrument products, readbacks, expressions, point
columns, backend-decoded results, and generated artifacts.

`outputs` are persisted measurements, artifacts, events, diagnostics, and
analysis inputs. The storage shape should be chosen by current needs rather
than frozen as a public layout.

## Point Identity

The current design distinguishes three concepts:

```text
point_index       dense logical row index for the segment
point_uid         logical identity derived from identity columns
execution_index   runtime order, retry order, or backend return order
```

`point_uid` should be derived from meaningful identity inputs such as
coordinates, entity refs, logical repeat, seed, and adaptive decision identity.
It should not include randomized execution order, backend batch id, operator
notes, transient runtime state, or local file paths.

Core point-column roles should stay small until repeated workflows prove the
need for stronger vocabulary:

```text
role: coordinate | auxiliary
identity: bool
ref: EntityRef | null
tags: list[str]
```

Concepts such as target, randomization, repeat, carry, and entity type can use
`identity`, `ref`, and tags for now.

## Configuration

Accepted configuration, run-time overrides, point-local patches, analysis
outputs, candidate changes, and live device readbacks are different things.

The working model is:

```text
accepted ConfigProfileSnapshot
  + RunRequest overrides
  + point-local ParameterPatch
  -> planning/runtime views
```

Candidate configuration changes come from analysis or adapters:

```text
analysis output
  -> ParameterChangeSet / ConfigPatch
  -> candidate ConfigProfileSnapshot
  -> preview / follow-up run / review
  -> explicit activation
```

Activation creates a new accepted configuration snapshot. Analysis,
instruments, instrument providers, and online decisions should not silently
mutate accepted configuration.

Importers for CSV, XLSX, JSON, registry trees, and private runner inputs are
anti-corruption tools. They should convert external formats into Scopecat
configuration or artifacts without making those external formats core design.

## Runtime

Runtime lowers a plan into a device program and performs side effects. Runtime
and instrument-group coordinators own:

- routing from logical resources to physical instruments;
- capability checks;
- desired-state diff and patch generation;
- uploads, arms, triggers, barriers, readbacks, acquisition commands, cleanup,
  and abort;
- retry, resume, failure handling, and backend point mapping.

An `Instrument` should stay thin. It declares capabilities, executes
device-local commands, and reports readbacks, products, events, and
diagnostics. It should not know the full experiment, config registry, analysis
policy, candidate review policy, or GUI state.

An `InstrumentGroup` models a coordinated stack such as AWG, ADC, LO, trigger,
clock, or a virtual lab provider. It can expose virtual fields and products
while internally mapping to one or more physical instruments.

## Data And Analysis

Structured runs and legacy capture should both produce inspectable evidence
under a run identity. The exact storage backend is an implementation choice.
JSON, JSONL, Parquet, Arrow, Zarr, HDF5, object storage, or content-addressed
storage can be introduced when they remove real friction.

Useful run evidence includes:

- request, config, spec, plan, and program identity when available;
- events, diagnostics, attachments, and operator context;
- result tables, arrays, readbacks, backend payloads, figures, reports, and
  external files;
- analysis records, candidate config patches, comparisons, and reviews.

Analysis should be able to start as manual notebook interpretation and later
be promoted into reusable steps. Manual analysis and promoted analysis should
share enough lineage that follow-up candidate configs and comparisons remain
auditable.

## Legacy Capture

`RunScope` / `TraceScope` is the low-intrusion path for existing notebooks and
scripts. The legacy code keeps execution control while Scopecat captures run
identity, inputs, config files or snapshots, generated artifacts, events,
measurements, notes, analysis, and a provenance level.

Capture records are evidence. They do not imply that Scopecat can replay the
run, and they should not pretend to have a structured spec, plan, or device
program unless those objects were actually produced.

Legacy hardware setup, upload, play, acquire, registry mutation, Data Vault
writes, GUI state, and background side effects should not shape the core model.

## Domain And GUI Deferral

Core should not encode one lab's qubit, pulse, device, registry, file naming,
or runner vocabulary. Domain vocabulary, compiler policy, pulse/circuit
semantics, instrument drivers, and private legacy behavior belong in examples,
private adapters, or future packages once a smaller useful boundary exists.

GUI/workbench work should present the same objects available from Python:
workspace, template, run request, run, data, analysis, candidate config,
comparison, and review. It should not invent GUI-only workflow state while the
experiment core is still changing.

## Current Bias

- Prefer a simpler internal shape over preserving old internal names.
- Keep structured execution and legacy capture visibly separate.
- Validate before side effects where practical.
- Treat local paths as storage details, not workflow identity.
- Promote abstractions only after real workflows repeat.
- Let tests and type checks identify everything that must move together after
  a breaking design change.
