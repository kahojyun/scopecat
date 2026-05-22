# Experiment Code Selection

## Status

Evidence-backed problem brief.

## User-Facing Failure

Experiment code, notebooks, helpers, generated companions, and local runtime
assumptions fragment into copied folders, backup variants, path hacks,
ambiguous notebooks, dirty working trees, nested helper copies, and weak
canonical identity. Users need to choose, restore, explain, or migrate the code
context that matters without adopting a full code registry, deployment system,
package manager, or general managed execution platform.

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
  internal Git state for early adoption; it does not mean the first selected
  code record should inspect Git.
- Calibration and experiment entrypoints are usually notebooks, selected files,
  or module functions rather than a project-level command. Some notebooks call
  a shared experiment header; others import broad helper sets and reload local
  modules.
- Reusable helper modules depend on import-time config, hardcoded local paths,
  local setting/data roots, LabRAD/Data Vault services, MMCS drivers,
  VISA-style instrument access, and private lab packages.
- Some notebook and helper entrypoints can mutate parameter files, initialize
  hardware runners, clear or reset devices, or connect to local services. A
  static selected-code record should mark mutation capability and must not
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

- The most important explicit record is likely the selected entrypoint or
  template/version used for a run.
- Snapshot-only capture may be too retrospective; preserving selected code
  references for later restore or version-selection validation may be the
  clearer workflow payoff.
- Early adoption should use minimal whitelist capture before dependency
  closure, registry semantics, or broad folder analysis.
- This is a staged adoption route: first record the code files and references
  users explicitly select as experiment-relevant, then let users migrate toward
  Scopecat-managed code workspaces when restore, compare, and version-selection
  behavior becomes valuable.
- A selected code reference should be usable by later run, handoff, or
  calibration-batch workflows; otherwise users may still have to manually
  reconstruct which code should run.
- Generated artifacts are useful context when they were actually selected or
  observed, but Scopecat should not infer a complete transformation pipeline
  from arbitrary user Python.
- Long term, Scopecat should manage experiment-code workspaces with Git-like
  versioning hidden behind lab-native actions such as save version, restore
  version, compare changes, mark useful, and use this version for a
  measurement. Users should not need to learn Git operations before Scopecat
  can manage code versions.
- Workflow or DAG structure may later help stable calibration routines, but it
  should not be the first code-versioning boundary. Start with selected root,
  explicit whitelist, stripped notebook sources, and named entrypoints; promote
  repeated stable entrypoints into workflow steps only after their inputs and
  outputs are clear.

## Derived Hypotheses

- Start with explicit selected root, entrypoint path and kind, whitelisted
  files, stripped notebook output policy, declared context references, and a
  broad non-recording policy for unwhitelisted files.
- Code-version selection should include a thin selected-version reference for
  future restore, version-selection, or review workflows, not only
  retrospective tracking.
- Environment validation should start as user-declared context references, not
  active readiness diagnostics or a general managed execution platform.
- Selected code context should be able to feed selected measurement export,
  selected-reference comparison, setup-binding review, and calibration
  continuation without making Scopecat own the user code or its runtime.
- Generated code-derived companions should be recorded as observed or selected
  artifacts only when explicitly whitelisted or linked, not recomputed
  automatically as part of the selected-code boundary.
- A first selected-code fixture should model the transition from messy external
  folder to selected code context to captured code-version candidate, without
  inspecting internal Git or deciding the final managed workspace store.

## Out Of Scope For This Brief

- Full dependency closure, process isolation platforms, code registries, Git
  hosting, automatic sync, deployment management, package management, and
  managed runner platforms.
- Inferring canonical status from folder names such as `old`, `backup`, `_bk`,
  `copy`, dated suffixes, person suffixes, or `temp`.
- Internal Git analysis, dirty-state warnings, nested-repository warnings, or
  default record-all file tracking in the first validation slice.
- Executing selected code, importing hardware-active modules, running notebooks,
  regenerating derived artifacts, or validating physical hardware state.
- Deep static dependency closure through arbitrary Python, notebook output,
  execution counts, or local service state.
- Required workflow/DAG structure or independently versioned function nodes.

## Possible Validation Questions

- Is selected root plus explicit entrypoint, whitelist, stripped notebook
  source, and captured code-version candidate enough to improve code version
  capture, recovery, and explanation?
- Can selected code references feed future restore or calibration-batch
  planning without Scopecat becoming a deployment or managed-runner system?
- Is selected root plus entrypoint plus explicit whitelist enough for a user to
  tell which code context should be restored or handed off?
- What captured state is useful first: stripped notebook source, file
  checksums, timestamped snapshot, archive, or user-selected bundle?
- Should the first fixture center a measurement/calibration entrypoint, or a
  role-labeled figure/analysis input set whose code explains how selected runs
  were assembled?
- Which generated companions should be merely linked as selected/observed
  artifacts, and which should be deferred until a later transformation or
  build-pipeline slice?
