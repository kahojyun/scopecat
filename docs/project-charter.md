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
- Persist operator intent and execution evidence, not compiler IR or runtime
  graphs. User-visible plan summaries are durable projections, not replayable
  executable specifications.
- Add abstractions only when they remove real complexity demonstrated by real
  workflows.

## Authoring and Persistence Boundaries

The user-facing authoring surface is the Python DSL: experiment templates,
invocations, scans, modules, and first-class typed values. Input, point, compute,
and parameter declarations produce opaque typed handles that are passed directly
through composition. Reusable config-dependent behavior belongs in modules, not
in a separate pre-experiment transformation phase. The complete value type
travels with each edge, allowing module wiring and scan values to be checked
without asking users to construct compiler-facing dataclasses or identify point
columns by strings.

Compilation turns that DSL into a transient `LinkedProgram`, then planning and
execution derive transient compiler and runtime graphs. Those objects are
implementation details and may evolve with the compiler. They are not storage
contracts, interchange formats, or replay inputs.

A structured run has four durable categories:

- the normalized `RunRequest`, which captures operator intent;
- the accepted configuration snapshot, which fixes the configuration used for
  the run;
- the `RunPlanRecord`, which projects the accepted plan into a user-visible,
  inspectable record without persisting compute nodes, payload topology, or
  runtime graph details; and
- execution evidence, including measurements, outcomes, diagnostics, and
  attached artifacts.

This boundary keeps auditability independent of compiler representation.
Reproducing a workflow means issuing authoring intent against accepted inputs
and compiling it again; it does not mean deserializing an old compiler or
runtime graph.

These categories are independent evidence, not one aggregate object. Readers
request the configuration, operator intent, accepted plan, or execution evidence
they actually need, so damage or absence in one category does not hide another.
Completed-run handles expose those first three records independently as
`config`, optional `request`, and `plan`; they do not reconstruct authoring
preview state from persisted evidence.
