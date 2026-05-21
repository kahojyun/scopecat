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

- Parallel top-level code snapshots contain overlapping `my_scripts`,
  `GateBased_PG`, `mqplot`, `Instrument_driver`, `util`, and plotting roots,
  with same-named files diverging across snapshots.
- Copied folders, backup variants, dated/person-suffixed notebooks, duplicate
  helpers, old/current branches, notebook checkpoints, pycache, archives, and
  nested backup subprojects are visible. These names are ambiguity evidence,
  not reliable canonical-status rules.
- At least one sample code root is a dirty Git repository, and a helper library
  root is a nested dirty Git repository. A selected code reference may need to
  distinguish committed version identity from observed working-tree state.
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
- Snapshot-only capture may be too retrospective; selection or loading of a
  previous version may be the clearer workflow payoff.
- Folder selection plus ignore rules may be enough before dependency closure or
  registry semantics.
- A selected code reference should be usable by later run, handoff, or
  calibration-batch workflows; otherwise users may still have to manually
  reconstruct which code should run.
- Generated artifacts are useful context when they were actually selected or
  observed, but Scopecat should not infer a complete transformation pipeline
  from arbitrary user Python.

## Derived Hypotheses

- Start with explicit selected root, entrypoint path and kind, optional selected
  symbol or notebook cell range, observed version state, include paths,
  exclude/classify rules, helper roots, config references, environment hints,
  service assumptions, private imports, mutation capability, generated
  companions, and redaction flags.
- Code-version selection should include a thin selected-version handoff for
  later local execution or review, not only retrospective tracking.
- Environment validation should mean selected-code readiness diagnostics and
  selected-code binding, not a general managed execution platform.
- Selected code context should be able to feed selected measurement export,
  selected-reference comparison, setup-binding review, and calibration
  continuation without making Scopecat own the user code or its runtime.
- Generated code-derived companions should be recorded as observed or selected
  artifacts with source/generator references, not recomputed automatically as
  part of the selected-code boundary.

## Out Of Scope For This Brief

- Full dependency closure, process isolation platforms, code registries, Git
  hosting, automatic sync, deployment management, package management, and
  managed runner platforms.
- Inferring canonical status from folder names such as `old`, `backup`, `_bk`,
  `copy`, dated suffixes, person suffixes, or `temp`.
- Executing selected code, importing hardware-active modules, running notebooks,
  regenerating derived artifacts, or validating physical hardware state.
- Deep static dependency closure through arbitrary Python, notebook output,
  execution counts, or local service state.

## Possible Validation Questions

- Is explicit entrypoint plus selected-folder snapshot enough to improve code
  selection, recovery, and explanation?
- Can selected code references feed later local run or calibration-batch steps
  without Scopecat becoming a deployment or managed-runner system?
- Is selected root plus entrypoint plus helper/include/exclude scope enough for
  a user to tell which code context should be restored or handed off?
- What observed version state is useful first: Git commit, dirty working-tree
  summary, file checksums, timestamped snapshot, or user-selected bundle?
- Should the first fixture center a measurement/calibration entrypoint, or a
  role-labeled figure/analysis input set whose code explains how selected runs
  were assembled?
- Which generated companions should be merely linked as selected/observed
  artifacts, and which should be deferred until a later transformation or
  build-pipeline slice?
