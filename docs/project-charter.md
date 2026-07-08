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
