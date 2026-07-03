# Scopecat Project Charter

Status: target design

Scopecat is a local-first Python platform for experiment measurement
workflows. It targets research labs that already rely on notebooks, scripts,
local configuration files, and instrument-specific code, but want structured,
auditable, and increasingly reproducible work without preserving legacy side
effects as public architecture.

The core package should stay domain-neutral. Domain-shaped examples,
instrument providers, compiler policy, and reusable analysis logic belong in
example support packages, private adapters, or future extensions until a real
boundary is worth extracting.

The project has no external compatibility contract today. When a cleaner model
is accepted, code, tests, fixtures, and docs should move decisively toward it
instead of accumulating compatibility layers.

## Problems To Solve

- Give notebook and script users stable Python APIs for local measurement
  workflows without making notebooks own durable workflow state.
- Record configuration, run requests, structured experiment definitions,
  execution plans, measurements, artifacts, events, diagnostics, analysis,
  candidate configs, comparisons, reviews, and operator context under one run
  identity.
- Keep accepted configuration separate from run-time overrides, analysis
  outputs, live device state, legacy registries, and GUI/session state.
- Support both native structured execution and low-intrusion capture of
  existing notebook/script workflows.
- Make raw data, derived data, analysis evidence, candidate changes, and review
  decisions first-class records rather than side effects of a runner.
- Provide explicit boundaries for configuration import, experiment authoring,
  planning, instrument/runtime execution, storage, analysis, candidate
  activation, GUI workbench behavior, and domain extensions.
- Keep lab-specific configuration, instrument details, private identifiers,
  and external runner quirks out of the open-source core model.

## Target Scope

Scopecat targets these local workflows:

- Open a workspace and resolve typed configuration snapshots without hardware
  side effects.
- Import or translate legacy config files, registry trees, spreadsheets, and
  private runner inputs through anti-corruption boundaries.
- Build structured experiments through reusable modules, runnable templates,
  explicit run requests, and closed per-segment experiment specs.
- Validate and dry-run structured work before side effects, including config,
  point identity, desired state, output records, result contracts, programs,
  routing, and capability compatibility.
- Execute native simulated or hardware runs through runtime, instrument groups,
  and thin instrument adapters.
- Capture legacy notebook/script runs through `RunScope` / `TraceScope` when
  reproducible native execution is not yet available.
- Persist raw and derived measurement datasets, typed artifacts, events,
  diagnostics, attachments, and provenance under a run manifest.
- Inspect run data through stable artifact ids, typed schemas, and result
  contracts rather than local file layout.
- Record exploratory notebook interpretation through `Analysis`, and promote
  repeated logic into `AnalysisStep`s.
- Produce candidate configuration patches from analysis, run follow-up
  candidates, compare runs, review evidence, and activate accepted config only
  through explicit decisions.
- Provide durable records that a future GUI/workbench can present without
  inventing GUI-only workflow state.

## Non-Goals

- Scopecat does not initially replace every legacy driver, notebook, runner,
  plotting helper, or analysis script.
- Scopecat does not preserve legacy hardware side effects, registry mutation,
  Data Vault writes, GUI globals, background plotters, or notebook global state
  as compatible behavior.
- Scopecat does not force legacy pulse, sequence, or backend-program
  generation code into a new IR before the boundary is proven.
- Scopecat core does not encode one laboratory's qubit, pulse, device,
  registry, file naming, or runner vocabulary.
- Scopecat does not require a central server, Kubernetes, or a database-backed
  deployment for first use.
- Scopecat core is not a full electronic lab notebook, LIMS, data warehouse,
  scheduler, plotting application, or general automation platform.

## Primary Users

- Experimental researchers who run measurements through notebooks, scripts,
  and helper libraries.
- Measurement engineers who maintain calibration workflows, instrument stacks,
  routing tables, configuration files, and data capture conventions.
- Lab software maintainers who need a path from legacy systems to a structured
  platform without freezing every legacy boundary.

Secondary users include domain extension authors, instrument adapter authors,
analysis-artifact tool authors, GUI/workbench builders, and research groups
adapting Scopecat to their own experiment domains.

## Design Principles

- Keep the core generic and domain-neutral.
- Optimize for local-first, Python-first workflows before distributed
  operations.
- Prefer explicit typed records over hidden mutable session objects.
- Keep notebooks useful but thin: they may compose work and add interpretation,
  but durable workflow state lives in Scopecat records.
- Make configuration declarative, immutable at run time, and validated before
  side effects.
- Treat accepted parameters and routing as configuration state, not live
  hardware state or private runner dictionaries.
- Make dry-run and simulation first-class paths, not testing shortcuts.
- Treat structured native execution and legacy capture as different contracts:
  one aims at reproducibility, the other at auditable evidence.
- Keep data and analysis independent enough that analysis can be manual,
  promoted, rerun, reviewed, and compared without rewriting raw run evidence.
- Require explicit review or activation for accepted configuration changes.
- Use stable ids, typed artifact refs, schemas, provenance, and diagnostics
  instead of local paths as durable identity.
- Make GUI/workbench actions correspond to notebook-accessible workflow
  records and APIs.
- Add abstractions only when they remove real complexity or protect a boundary
  demonstrated by real workflows.

## Structured Experiment Direction

Structured native experiments are a central UX path, but they are one part of
the platform. Their target architecture is:

```text
ExperimentModule + ExperimentTemplate + RunRequest + ConfigSnapshot
  -> ExperimentSpec
  -> ExperimentPlan
  -> DeviceProgram
  -> InstrumentRuntime
  -> InstrumentGroup / Instrument
```

The important charter-level rule is that structured runs compile into closed,
auditable segment records before side effects. Details such as point identity,
record declarations, result contracts, device programs, code islands, and
adaptive point sources are defined in [Architecture](architecture.md) and
[Experiment workflow](experiment-workflow.md), not in this charter.

## Data, Analysis, And Review Direction

Scopecat should make measurement evidence and interpretation durable without
turning every notebook into production code.

Raw measurements, backend payloads, readbacks, generated programs, figures,
tables, arrays, reports, and external files are artifacts with stable ids and
typed metadata. Analysis records declare their inputs and outputs so manual
interpretation and promoted steps share the same lineage model.

Candidate configs are reviewable configuration patches backed by evidence.
Resolving a candidate is a system step; accepting it is an explicit activation
decision. Historical runs, artifacts, analysis, reviews, and activation records
remain immutable.

## Legacy Migration Boundary

Legacy support has two primary paths.

`RunScope` / `TraceScope` is the main low-intrusion path. A legacy notebook or
script keeps execution control while Scopecat captures run identity, inputs,
config files or snapshots, generated artifacts, events, measurements, notes,
analysis, and provenance level. This is capture, not reproducible execution.

Native migration extracts pure or pure-ish pieces into Scopecat modules or
adapters:

- settings and config generation;
- sweep construction;
- sequence and pulse construction;
- waveform or backend-program generation;
- dataset schema and metadata construction;
- analysis-to-candidate calculations.

Legacy hardware connection, setup, upload, play, acquire, registry mutation,
data-vault writes, GUI state, and background side effects are not migrated into
core contracts. If a legacy runner has a stable batch boundary, it may be
wrapped as an optional backend or instrument-group adapter, but it must not
shape core records around legacy compatibility.
