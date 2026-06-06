# Experiment Code Recording

## Status

Evidence-backed problem brief.

This brief preserves evidence only. Current journey/use-case ownership lives
in [`../../product/target-journeys.md`](../../product/target-journeys.md);
validation evidence lives in
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md).

## User-Facing Failure

Experiment code, notebooks, helpers, generated companions, and local runtime
assumptions fragment into copied folders, backup variants, path hacks,
ambiguous notebooks, dirty working trees, nested helper copies, and weak
canonical identity. Users first need a low-friction record of which code
context was associated with a run, calibration step, handoff,
or comparison. They should not have to curate the correct code selection up
front, migrate into a managed workspace, or adopt a full code registry,
deployment system, package manager, or general managed execution platform
before Scopecat can preserve useful code context.

## Observed Sample Evidence

- Parallel top-level code snapshots contain overlapping helper-module,
  pulse-generation, plotting, instrument-driver, utility, and analysis roots,
  with same-purpose files diverging across snapshots.
- Copied folders, backup variants, dated/person-suffixed notebooks, duplicate
  helpers, old/current branches, notebook checkpoints, pycache, archives, and
  nested backup subprojects are visible. These names are ambiguity evidence,
  not reliable canonical-status rules.
- At least one sample code root is a dirty Git repository, and a helper library
  root is a nested dirty Git repository. This is evidence against relying on
  internal Git state for early adoption; it does not mean the first recorded
  code context should inspect Git.
- Calibration and experiment entrypoints are usually notebooks, explicit files,
  or module functions rather than a project-level command. Some notebooks call
  a shared experiment header; others import broad helper sets and reload local
  modules.
- Reusable helper modules depend on import-time config, hardcoded local paths,
  local setting/data roots, LabRAD/Data Vault services, MMCS drivers,
  VISA-style instrument access, and private lab packages.
- Some notebook and helper entrypoints can mutate parameter files, initialize
  hardware runners, clear or reset devices, or connect to local services. A
  static code snapshot record should mark mutation capability and must not
  execute sample code.
- Parameter, wiring, circuit, and pulse helpers generate derived companions
  such as parameter snapshots, chip or line info, registry-like setup maps,
  circuit JSON, and waveform-adjacent compile state. These artifacts need
  generator/source provenance and should not be silently regenerated during
  export or comparison.
- Analysis code links measurements through session/path plus legacy numeric
  IDs, encoded filenames/titles, `.ini` sidecars, copied parameter snapshots,
  explicit ID ranges, role-labeled ID lists, curated files, and derived arrays.
  Dataset ID alone is not enough code/data context.

## Project-Owner Clarification

- The first adoption step should be recording, not selection. Scopecat should
  capture explicit code context associated with a run or calibration step
  before asking users to curate a durable "right" selection.
- The most important explicit record is likely the entrypoint, template, or
  code version associated with a run, plus enough surrounding context to know
  how that association was made.
- Snapshot-only capture may be too retrospective if it is disconnected from
  run/step intent. The first useful record should preserve both the
  point-in-time code snapshot record and the run, step, handoff, or
  comparison context that made it relevant.
- The base product concept should be `code_context`: the code root or
  workspace, entrypoint, included source observations or snapshot reference,
  and declared context references associated with a run or step. `Recorded`
  is the audit/provenance state of that context, not the name of every future
  active code workspace.
- A future active path should distinguish a selected code snapshot or managed
  code version from a concrete `materialized_code_workspace`. The first fixture
  does not load or expand a saved code snapshot; it only records the current
  context.
- Early adoption should use minimal explicit recording before dependency
  closure, registry semantics, broad folder analysis, or restore UX. An
  explicit include list can be one recording policy, but it should not make
  manual selection the product's first adoption gate.
- This is a staged adoption route: first record code context as ordinary
  experiment context, then let users promote, compare, restore, or migrate
  those records toward Scopecat-managed code workspaces when version-selection
  behavior becomes valuable.
- Recorded code context should be usable by later run, handoff, or
  calibration-batch workflows; otherwise users may still have to manually
  reconstruct which code was used or should be restored.
- Generated artifacts are useful context when they were actually selected or
  observed, but Scopecat should not infer a complete transformation pipeline
  from arbitrary user Python.
- Long term, Scopecat should manage experiment-code workspaces with Git-like
  versioning hidden behind lab-native actions such as save version, restore
  version, compare changes, mark useful, and use this version for a
  measurement. Users should not need to learn Git operations before Scopecat
  can manage code versions.
- Workflow or DAG structure may later help stable calibration routines, but it
  should not be the first code-recording boundary. Start with recorded root or
  source reference, entrypoint, explicit include policy, stripped notebook
  sources when captured, and named run/step context; promote repeated stable
  entrypoints into workflow steps only after their inputs and outputs are
  clear.

## Derived Hypotheses

- Start with explicit code records: root or source reference, entrypoint path
  and kind, include policy, recorded files or source observations, stripped
  notebook output policy when notebooks are captured, declared context
  references, and a broad non-recording policy for unrecorded files.
- Code snapshot records should include enough run/step relevance to support
  future restore, version-selection, or review workflows, not only
  retrospective file tracking.
- Environment validation should start as user-declared context references, not
  active readiness diagnostics or a general managed execution platform.
- Recorded code context should be able to feed selected measurement export,
  selected-reference comparison, setup-binding review, and calibration
  continuation without making Scopecat own the user code or its runtime.
- Generated code-derived companions should be recorded as observed, referenced,
  or explicitly included artifacts only when linked by the run/step record, not
  recomputed automatically as part of the code-recording boundary.
- A first code-recording fixture should model the transition from messy
  external folder to recorded run/step code context to code snapshot record,
  without inspecting internal Git or deciding the final managed workspace
  store.

## Out Of Scope For This Brief

- Full dependency closure, process isolation platforms, code registries, Git
  hosting, automatic sync, deployment management, package management, and
  managed runner platforms.
- Inferring canonical status from folder names such as `old`, `backup`, `_bk`,
  `copy`, dated suffixes, person suffixes, or `temp`.
- Internal Git analysis, dirty-state warnings, nested-repository warnings, or
  default record-all file tracking in the first validation slice.
- Requiring users to decide the authoritative code selection before Scopecat
  can record useful run/step code context.
- Executing recorded code, importing hardware-active modules, running notebooks,
  regenerating derived artifacts, or validating physical hardware state.
- Deep static dependency closure through arbitrary Python, notebook output,
  execution counts, or local service state.
- Required workflow/DAG structure or independently versioned function nodes.

## Possible Validation Questions

- Is recorded root/source reference plus explicit entrypoint, include policy,
  stripped notebook source, and code snapshot record enough to
  improve code recording, recovery, and explanation?
- Can recorded code references feed future restore or calibration-batch
  planning without Scopecat becoming a deployment or managed-runner system?
- Is recorded root/source reference plus entrypoint plus explicit include
  policy enough for a user to tell which code context was used, should be
  restored, or should be handed off?
- What snapshot payload is useful first: stripped notebook source, file
  checksums, timestamped snapshot, archive, or run/step-linked bundle?
- Should the first fixture center a measurement/calibration entrypoint, or a
  role-labeled figure/analysis input set whose code explains how selected runs
  were assembled?
- Which generated companions should be merely linked as recorded/observed
  artifacts, and which should be deferred until a later transformation or
  build-pipeline slice?
