# Code Selection Readiness

## Status

Evidence-backed problem brief.

## User-Facing Failure

Experiment code, notebooks, helpers, and local runtime assumptions fragment
into copied folders, backup variants, path hacks, ambiguous notebooks, and weak
canonical identity. Users need to choose, restore, explain, or migrate the code
that matters without adopting a full code registry or managed execution system.

## Observed Sample Evidence

- Copied folders, backup variants, duplicate helpers, old/current branches,
  notebook copies, checkpoints, pycache, and archives are visible.
- Local runbooks, conda exports, hardcoded Windows paths, private packages,
  local service assumptions, registry endpoints, and import-time loads show
  readiness pressure.
- Notebook source cells can be ambiguous or mutation-capable; notebook outputs
  and execution counts are not reliable records of what ran.

## Project-Owner Clarification

- The most important explicit record is likely the selected entrypoint or
  template/version used for a run.
- Snapshot-only capture may be too retrospective; selection or loading of a
  previous version may be the clearer workflow payoff.
- Folder selection plus ignore rules may be enough before dependency closure or
  registry semantics.

## Derived Hypotheses

- Start with explicit selected folder, entrypoint, snapshot/checkpoint,
  duplicate/copy ambiguity, and readiness notes.
- Code-version selection should distinguish tracking-only value from future
  load-selected-version value.
- Readiness should be fail-before-write diagnostics, not managed execution.

## Out Of Scope For This Brief

- Dependency closure, process isolation, code registries, Git hosting,
  automatic sync, deployment management, and managed runners.
- Inferring canonical status from folder names such as `old`, `backup`, `_bk`,
  `copy`, or `temp`.

## Possible Validation Questions

- Is explicit entrypoint plus selected-folder snapshot enough to improve code
  selection, recovery, and explanation?
- If tracking-only is too weak, what minimum selected-version workflow creates
  value before Scopecat owns process execution?
