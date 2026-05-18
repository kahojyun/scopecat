# Experiment Code Selection

## Status

Evidence-backed problem brief.

## User-Facing Failure

Experiment code, notebooks, helpers, and local runtime assumptions fragment
into copied folders, backup variants, path hacks, ambiguous notebooks, and weak
canonical identity. Users need to choose, restore, explain, or migrate the code
that matters without adopting a full code registry, deployment system, or
general managed execution platform.

## Observed Sample Evidence

- Copied folders, backup variants, duplicate helpers, old/current branches,
  notebook copies, checkpoints, pycache, and archives are visible.
- Local runbooks, conda exports, hardcoded Windows paths, private packages,
  local service assumptions, registry endpoints, and import-time loads show
  environment validation pressure.
- Notebook source cells can be ambiguous or mutation-capable; notebook outputs
  and execution counts are not reliable records of what ran.

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

## Derived Hypotheses

- Start with explicit selected folder, entrypoint, snapshot/checkpoint,
  duplicate/copy ambiguity, and environment notes.
- Code-version selection should include a thin selected-version handoff for
  later local execution, not only retrospective tracking.
- Environment validation should be fail-before-write diagnostics and
  selected-code binding, not a general managed execution platform.

## Out Of Scope For This Brief

- Full dependency closure, process isolation platforms, code registries, Git
  hosting, automatic sync, deployment management, and managed runner platforms.
- Inferring canonical status from folder names such as `old`, `backup`, `_bk`,
  `copy`, or `temp`.

## Possible Validation Questions

- Is explicit entrypoint plus selected-folder snapshot enough to improve code
  selection, recovery, and explanation?
- Can selected code references feed later local run or calibration-batch steps
  without Scopecat becoming a deployment or managed-runner system?
