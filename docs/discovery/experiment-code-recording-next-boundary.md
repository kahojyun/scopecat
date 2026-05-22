# Experiment Code Recording Next Boundary

## Status

Discovery boundary note, not an ADR.

This note closes the current experiment-code recording slice by separating what
the first adoption path has earned from what should trigger a later managed
workspace or environment-restoration slice.

## Earned Now

The current slice earns a recording-first path for experiment code
version/snapshot records:

- users can record the external code root, entrypoint, explicitly included
  files, and declared context references associated with a measurement or
  calibration step;
- Scopecat can record that context without inspecting internal Git state,
  scanning unrecorded files, or analyzing the whole legacy codebase;
- included notebooks can be recorded as source without outputs;
- unrecorded files, backups, caches, checkpoints, generated files, and copied
  helper folders remain outside the record unless the user records or links
  them;
- the recorded code context can be referenced by measurement export,
  selected-reference comparison, setup-binding review, and calibration
  continuation;
- a captured code-version record can name the future Scopecat-managed
  capture scope without accepting storage, restore, merge, sync, or execution
  contracts.

This is enough to cover the first adoption value: record the code most directly
tied to experiment workflow and intent while avoiding legacy-codebase analysis.
Selection can later choose, promote, or restore one of those records; it should
not be the first adoption gate.

## Not Earned Yet

The current slice does not earn:

- final managed workspace storage;
- a file snapshot, checksum, archive, or content-addressed store contract;
- a Git replacement implementation;
- internal Git diagnostics as product output;
- default record-all file tracking;
- branch, merge, conflict, push, pull, sync, or collaboration semantics;
- package or environment ownership;
- loading a recorded code version for execution;
- `uv sync` or lockfile-driven environment restoration;
- notebook execution, code import, dependency discovery, or hardware readiness
  checks;
- workflow/DAG nodes, component-level code versions, or compatibility
  contracts;
- generated artifact regeneration or build-pipeline validation;
- GUI design.

These remain plausible future capabilities. They are not required for the
first recorded code version/snapshot record to be useful.

## Adoption Route

The intended product route is staged:

1. Start with explicit run/step code version/snapshot records over messy
   external folders.
2. Let those records connect measurements, calibration steps, handoff packages,
   and comparison workflows to the code context users actually used or
   observed.
3. Let users move recorded code into Scopecat-managed workspaces when restore,
   compare, and version selection become valuable.
4. After managed workspace storage is earned, evaluate selected-version loading
   and declared environment restoration.
5. After environment authority is earned, evaluate lockfile-driven dependency
   sync, readiness checks, and managed runners.

The first stage should remain useful even if a lab never adopts the later
managed-workspace stages.

## Triggers For The Next Slice

A managed-workspace slice is worth starting when the first adoption path needs
one of these user-visible behaviors:

- restore this recorded code context on the same or another machine;
- compare the current editable code with a previously captured code-version record;
- choose a saved code version at measurement start;
- materialize a selected version into an editable workspace;
- protect users from accidentally modifying the only useful copy of selected
  experiment code;
- move from external-folder references to Scopecat-owned code storage.

An environment-restoration slice is worth starting only after managed
workspace storage has a candidate boundary and the user-visible question is
about runnable context rather than record context. Useful triggers include:

- users need to know whether a recorded code version can be loaded;
- the recorded code version declares an environment file or lockfile;
- restoring a code version without its environment is not enough to resume the
  experiment workflow;
- `uv sync` or another declared environment operation becomes part of the
  expected restore flow;
- readiness checks can be performed without importing hardware-active user
  modules or executing experiment code.

## First Future Fixture Candidates

Potential managed-workspace fixture:

- input: a captured code-version record with included files and stripped
  notebooks;
- output: a managed code version summary with stable identity, file inventory,
  content-integrity hints, and materialization intent;
- boundary: no Git UI, no merge model, no dependency install, no execution.

Potential environment-restore fixture:

- input: a managed code version plus a user-declared environment file or
  lockfile reference;
- output: restore/readiness summary that says what would be synced or checked;
- boundary: no hardware import, no notebook execution, no claim that the
  experiment result is reproducible.

Both fixtures should keep code execution separate from code record integrity.
