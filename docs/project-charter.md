# Scopecat Project Charter

Status: direction

Scopecat is a local-first Python platform for experiment measurement
workflows. It targets research labs that already rely on notebooks, scripts,
local configuration files, and instrument-specific code, but want structured,
auditable, and increasingly reproducible work without freezing legacy side
effects into the core model.

The core package should stay domain-neutral. Domain-shaped examples,
instrument providers, compiler policy, and reusable analysis logic belong in
example support packages, private adapters, or future extensions until a real
need is proven by repeated local workflows.

The project has no external compatibility contract today. When a cleaner model
is accepted, code, tests, fixtures, and docs should move decisively toward it
instead of accumulating compatibility layers.

## Problems To Solve

Scopecat should make it practical to:

- run local experiment workflows from Python without letting notebooks become
  the only owner of workflow state;
- compile structured experiment requests into auditable inputs before hardware
  side effects;
- keep accepted configuration separate from run overrides, point-local patches,
  analysis outputs, live device state, legacy registries, and GUI state;
- capture legacy notebook/script runs with low intrusion when structured
  execution is not yet available;
- make raw data, derived data, analysis evidence, and candidate changes visible
  enough to audit;
- keep lab-specific configuration, instrument details, private identifiers, and
  external runner quirks out of the open-source core model.

## Non-Goals

- Scopecat does not initially replace every legacy driver, notebook, runner,
  plotting helper, or analysis script.
- Scopecat does not preserve legacy hardware side effects, registry mutation,
  Data Vault writes, GUI globals, background plotters, or notebook global state
  as compatible behavior.
- Scopecat does not force legacy pulse, sequence, or backend-program generation
  code into a new IR before the need is proven.
- Scopecat core does not encode one laboratory's qubit, pulse, device,
  registry, file naming, or runner vocabulary.
- Scopecat does not require a central server, Kubernetes, or a database-backed
  deployment for first use.
- Scopecat core is not a full electronic lab notebook, LIMS, data warehouse,
  scheduler, plotting application, or general automation platform.

## Design Principles

- Keep the core generic and domain-neutral.
- Optimize for local-first, Python-first workflows before distributed
  operations.
- Prefer explicit typed records over hidden mutable session objects.
- Keep notebooks useful but thin: they may compose work and add interpretation.
- Make configuration declarative, immutable at run time, and validated before
  side effects.
- Treat structured execution and legacy capture as different modes: one aims at
  reproducibility, the other at auditable evidence.
- Keep data and analysis independent enough that analysis can be manual first
  and promoted later.
- Require explicit activation for accepted configuration changes.
- Prefer logical artifact names, typed metadata, provenance, and diagnostics
  over local paths as workflow identity.
- Add abstractions only when they remove real complexity demonstrated by real
  workflows.

## Structured Experiment Direction

Structured experiments are a central UX path, but they are one part of
the platform. The active design direction is:

```text
ExperimentModule + ExperimentTemplate + RunRequest + ConfigProfileSnapshot
  -> ExperimentSpec
  -> ExperimentPlan
  -> DeviceProgram
  -> InstrumentRuntime
  -> InstrumentGroup / Instrument
```

The charter-level rule is that structured runs should compile into closed,
auditable segment inputs before side effects. The current working model lives
in [Experiment core](experiment-core.md).

## Data And Analysis Direction

Scopecat should make measurement evidence and interpretation inspectable
without turning every notebook into production code.

Raw measurements, backend payloads, readbacks, generated programs, figures,
tables, arrays, reports, and external files are artifacts with typed metadata
where useful. Analysis records should be able to declare inputs and outputs so
manual interpretation and promoted steps can share the same lineage model.

Candidate configs are reviewable configuration patches backed by evidence.
Accepting one is an explicit activation decision. Historical evidence should
not be rewritten to hide how a decision was made.

## Legacy Migration Boundary

`RunScope` / `TraceScope` is the main low-intrusion path. A legacy notebook or
script keeps execution control while Scopecat captures run identity, inputs,
config files or snapshots, generated artifacts, events, measurements, notes,
analysis, and provenance level. This is capture, not reproducible execution.

Structured migration should extract pure or pure-ish pieces into Scopecat
modules or adapters: settings and config generation, sweep construction,
sequence or pulse construction, backend-program generation, dataset metadata,
and analysis-to-candidate calculations.

Legacy hardware connection, setup, upload, play, acquire, registry mutation,
data-vault writes, GUI state, and background side effects are not migrated into
core. If a legacy runner has a useful batch boundary, it may be wrapped behind
an instrument group, but it should not shape the core model around legacy
compatibility.
