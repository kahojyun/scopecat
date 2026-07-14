# Scopecat Project Charter

Scopecat is a local-first Python platform for experiment measurement workflows.
It is for research labs that already rely on notebooks, scripts, local
configuration, and instrument-specific code, but want their work to become more
structured, auditable, and reproducible over time.

## Long-Term Goals

Scopecat should make it practical to:

- run local experiments from Python without making a notebook the sole owner
  of workflow state;
- describe intent and validate accepted inputs before hardware side effects;
- preserve enough operator intent, configuration, data, analysis, and effect
  evidence to understand what happened after a run;
- keep configuration changes explicit and reviewable instead of hiding them in
  mutable sessions or device state;
- support manual analysis first and let repeated work grow into reusable
  workflows without changing the evidence model;
- let laboratories integrate domain semantics and hardware targets without
  putting their private vocabulary, wiring, or provider policy into core;
- remain useful in a local Python environment while leaving room for proven
  execution and storage needs to grow behind explicit boundaries.

## Enduring Principles

- Keep core domain-neutral and Python-first.
- Prefer explicit typed values and immutable records over hidden mutable
  session objects.
- Keep notebooks useful but thin: they may compose work and add
  interpretation, while durable workflow state lives elsewhere.
- Validate configuration and provider contracts before effects; represent
  uncertain effects honestly and require reconciliation before unsafe retry.
- Keep raw data, derived data, analysis evidence, and candidate configuration
  changes independently inspectable.
- Require explicit activation for accepted configuration changes.
- Persist operator intent and execution evidence, not compiler or runtime
  graphs. A user-visible plan is an inspectable projection, not a replay
  program.
- Prefer logical identities, typed metadata, provenance, and structured
  problems over local paths or delimiter-packed names as workflow identity.
- Add abstractions only when repeated workflows demonstrate that they remove
  real complexity.
- When a cleaner model wins, update code, tests, fixtures, and documentation
  together instead of preserving unused internal compatibility layers.

## Non-Goals

- Replacing every legacy driver, notebook, runner, plotting helper, or analysis
  script.
- Preserving legacy side effects, global state, registry mutation, or external
  storage behavior as compatibility contracts.
- Forcing every domain program, pulse sequence, or backend into one universal
  core intermediate representation.
- Encoding a laboratory's qubits, devices, file naming, registries, or runner
  vocabulary in the core package.
- Requiring a central server, cluster scheduler, or database-backed deployment
  for first use.
- Becoming a full electronic lab notebook, LIMS, data warehouse, plotting
  application, or general automation platform.
