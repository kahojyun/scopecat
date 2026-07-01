# Scopecat Project Charter

Status: Current direction

Scopecat is a local-first Python platform for experiment measurement workflows.
It is aimed at research labs that already rely on notebooks, scripts, ad hoc
configuration files, and instrument-specific control code, and need a path to
more reproducible runs without rewriting everything up front.

The core package should stay domain-neutral. Domain-shaped examples,
instrument providers, and reusable analysis logic belong in example support
packages or future extensions until a real boundary is worth extracting.

## Problems To Solve

- Make experiment runs reproducible by recording configuration, plans,
  measurements, artifacts, logs, analysis records, candidate configs,
  comparisons, and reports under one run identity.
- Let notebook and script workflows call stable Python APIs instead of owning
  durable workflow state.
- Keep lab-specific configuration, instrument details, and private adapters out
  of the open-source core.
- Support dry-run and simulated execution so workflows can be validated without
  real hardware.
- Provide explicit boundaries for native instruments, brownfield runner
  adapters, analysis steps, candidate config review, and local storage.

## Target Scope

Scopecat targets these local workflows:

- Resolve and validate configuration snapshots without hardware side effects.
- Resolve accepted parameters into deterministic parameter build snapshots,
  including scalar values, table values, derived values, provenance, and
  diagnostics.
- Build experiments through `Workspace.experiment(...)`, lowering to durable
  `ExperimentSpec` records for planning, fixtures, and adapter boundaries.
- Expand experiments into sweep plans, desired-state plans, state patches, and
  acquisition plans.
- Run dry or native simulated executions through local storage.
- Persist raw and derived measurement datasets, typed artifacts, events, and
  reports under a run manifest.
- Inspect run data through a `Data` view.
- Capture exploratory notebook interpretation through `Analysis`.
- Promote repeated analysis into `AnalysisStep`s.
- Review analysis-backed candidate configs through internal parameter change
  records.
- Compare baseline and candidate runs after candidate configuration changes.

## Non-Goals

- Scopecat does not initially replace every legacy driver, notebook, or
  analysis script.
- Scopecat does not encode assumptions from one laboratory setup into the core.
- Scopecat does not require a central server, Kubernetes, or a complex
  operations stack for first use.
- Scopecat does not treat notebooks as the source of truth for production
  measurement logic.
- Scopecat does not expose private machine names, local paths, instrument
  addresses, chip labels, or lab-specific identifiers in public examples or
  docs.
- Scopecat is not a full electronic lab notebook, LIMS, or data warehouse.

## Primary Users

- Experimental researchers who currently run measurements through notebooks,
  scripts, and instrument-specific helper libraries.
- Measurement engineers who maintain calibration workflows, instrument
  integrations, configuration files, and data capture conventions.
- Lab software maintainers who need a migration path from legacy systems to a
  more structured platform.

Secondary users include extension authors, analysis-artifact tool authors, and
research groups adapting Scopecat to their own experiment domains.

## Architecture Principles

- Keep the core generic; put domain-specific behavior in adapters, examples, or
  extensions.
- Prefer ports and adapters over direct dependencies on legacy code.
- Keep configuration declarative and validate it before execution.
- Treat parameters as accepted configuration state and deterministic planning
  inputs, not as live hardware state or private runner dictionaries.
- Make dry-run a first-class path, not a testing shortcut.
- Keep acquisition intent separate from analysis, review, and candidate config
  policy.
- Record enough metadata to reproduce or audit a run later.
- Keep notebooks useful but thin.
- Use simulated instruments and golden datasets in CI.
- Avoid copying legacy naming, paths, and private identifiers into public docs.
- Add abstractions only when they remove real migration or maintenance friction.

## Legacy Migration Boundary

Brownfield integrations should preserve existing operational behavior behind
adapters while translating useful state into Scopecat records.

Adapter work should focus on:

- Config and input validation.
- Explicit parameter import and mapping from legacy JSON, tables, registries,
  and runner-specific structures into Scopecat-owned models.
- Run metadata capture.
- Dry-run behavior.
- Legacy script or API execution through explicit mapping.
- Preservation of legacy output as artifacts.
- Structured measurement recording when feasible.
- Diagnostics that explain what could not be translated.

Native Scopecat control should evolve separately through the instrument
protocol, desired-state plans, and typed acquisition models. The migration path
is wrap first, then replace targeted pieces when the replacement removes real
complexity.

## Parameter System Direction

The canonical architecture is defined in [Scopecat Architecture](architecture.md),
with parameter details in [Parameter System](parameter-system.md). The short
version is:

- `ParameterState` stores accepted source values for future runs.
- Parameter tables are first-class configuration state, not spreadsheet
  sidecars.
- Deterministic derivation recipes produce derived parameter build snapshots
  before planning.
- Planning consumes parameter build snapshots and emits desired-state plans.
- Analysis and promoted analysis steps produce candidate configs instead of
  writing active state directly.
- CSV, XLSX, LabRAD registry, and legacy JSON support belongs in importers or
  private adapters that output typed Scopecat models and diagnostics.
