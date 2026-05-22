# Experiment Code Recording Next Boundary

## Status

Discovery boundary note, not an ADR.

This note closes the current experiment-code recording slice by separating what
the first adoption path has earned from what should trigger a later managed
workspace or environment-restoration slice.

## Earned Now

The current slice earns a recording-first path for experiment code contexts
and code snapshot records:

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
- a code snapshot record can name the future Scopecat-managed snapshot scope
  without accepting storage, restore, merge, sync, or execution contracts.

`Recorded` names the audit state of a code context. It should not become the
name for a future active workspace that Scopecat materializes. A later managed
path should distinguish the selected snapshot/version from the concrete
materialized code workspace.

Code records should also distinguish capture state. Some included items may be
content-captured, while others may be reference-only, missing, redacted, or
excluded. That is acceptable for early adoption as long as comparison and
restore surfaces show the limitation instead of pretending all included items
are equally recoverable or comparable.

This is enough to cover the first adoption value: record the code most directly
tied to experiment workflow and intent while avoiding legacy-codebase analysis.
Selection can later choose, promote, or restore one of those records; it should
not be the first adoption gate.

The transition into managed code should be explicit rather than pretending that
recorded history and managed history are one continuous version line:

```text
recorded code context
  -> code snapshot record with capture-state facts
  -> promoted managed code version
  -> materialized editable workspace
```

Only captured or recaptured content should become a strong managed-version
inventory. Reference-only prior records can remain useful evidence, but they
should carry unverified or not-compared findings when users ask for content
comparison.

## Not Earned Yet

The current slice does not earn:

- final managed workspace storage;
- a file snapshot, checksum, archive, or content-addressed store contract;
- a Git replacement implementation;
- internal Git diagnostics as product output;
- default record-all file tracking;
- branch, merge, conflict, push, pull, sync, or collaboration semantics;
- package or environment ownership;
- loading a selected code snapshot or managed code version for execution;
- `uv sync` or lockfile-driven environment restoration;
- notebook execution, code import, dependency discovery, or hardware readiness
  checks;
- workflow/DAG nodes, component-level code versions, or compatibility
  contracts;
- generated artifact regeneration or build-pipeline validation;
- GUI design.

These remain plausible future capabilities. They are not required for the
first code snapshot record to be useful.

## Adoption Route

The intended user adoption route is value-driven, not a strict validation
dependency chain:

1. Start with explicit run/step code contexts and code snapshot records over
   messy external folders, without requiring users to move code into Scopecat.
2. Let those records connect measurements, calibration steps, handoff packages,
   and comparison workflows to the code context users actually used or
   observed.
3. Let users promote captured or recaptured code snapshot records into managed
   code versions when stable identity, inventory, restore, compare, or version
   selection becomes valuable.
4. From managed versions, let users branch into the workflows they need:
   comparison, workspace materialization, editable-folder observation, run
   preparation, rerun preparation, or environment help.
5. Treat dependency sync, execution readiness, and managed runners as later
   adoption only for labs that want Scopecat to help prepare runnable managed
   contexts.

The first stage should remain useful even if a lab never adopts the later
managed-workspace stages. A lab also does not need to adopt comparison,
materialization, run preparation, and environment support in one linear product
journey.

## Validation Slice Order

Validation should follow authority boundaries more strictly than user adoption:

1. Validate a comparable code surface over explicit code facts before claiming
   a general diff, editable-folder readiness, or runnable context.
2. Validate workspace materialization intent before creating editable
   workspaces.
3. Validate workspace materialization before treating a current editable folder
   as a managed-version readiness target.
4. Validate editable-folder observation against a selected managed version or
   materialized workspace before preparing a run context.
5. Validate prepared run context from selected code or workspace, selected
   parameter state, setup binding, and measurement intent.
6. Validate reference-based rerun preparation as a convenience workflow over
   prepared run context, not as a separate reproducibility claim.
7. Validate declared environment inventory before environment readiness or
   dependency sync.
8. Only after those boundaries prove useful, validate environment readiness,
   dependency sync, and managed runners.

## Triggers And Order For Future Slices

Future validation slices should stay separated by the authority they need. Use
these triggers to decide which slice to design next, not as a mandatory user
journey.

A comparable-code-surface slice is worth starting when the user-visible need is:

- compare available recorded or managed code facts without pretending
  reference-only items support content diff;
- explain why two code records are same-observed, changed, missing,
  reference-only, redacted, excluded, or not-compared;
- keep comparison useful before any editable workspace exists.

A workspace-materialization-intent slice is worth starting when the need is:

- preview where a selected managed version would be materialized;
- detect destination naming, collision, overwrite, and provenance-label issues
  before writing files;
- protect users from accidentally modifying the only useful copy of selected
  experiment code.

A workspace-materialization slice is worth starting when the need is:

- restore this code snapshot record on the same or another machine;
- materialize a selected version into an editable workspace;
- move from external-folder references to Scopecat-owned code storage.

An editable-folder-observation slice is worth starting after materialization
or managed storage authority exists and the need is:

- check whether the current editable folder matches a selected managed version
  before the user runs or edits it;
- compare observed file facts without accepting Git diff, semantic source diff,
  dependency readiness, import, or execution.

A prepared-run-context slice is worth starting when the need is:

- prepare a run context from selected code, parameter state, setup binding, and
  measurement intent so the user can run existing lab code outside Scopecat;

A reference-based rerun-preparation slice is worth starting after prepared run
context is useful and the need is:

- start from a selected reference measurement and prepare the matching managed
  code version plus context for a manual rerun;
- reuse the same run-context assembly without claiming reproducibility or
  automatic cause attribution.

A declared-environment-inventory slice should come before environment
readiness. It is worth starting when the user-visible need is:

- record declared environment files, lockfiles, interpreter hints, or
  package-manager hints next to the selected code context;
- explain which declared environment facts are present or missing without
  syncing, importing, or checking runnable readiness.

An environment-readiness or sync slice is worth starting only after managed
workspace and declared-environment authority have candidate boundaries and the
user-visible question is about runnable context rather than record context.
Useful triggers include:

- users need to know whether a selected code snapshot or managed code version
  can be loaded;
- the selected code snapshot or managed code version declares an environment
  file or lockfile;
- restoring a code version without its environment is not enough to resume the
  experiment workflow;
- `uv sync` or another declared environment operation becomes part of the
  expected restore flow;
- readiness checks can be performed without importing hardware-active user
  modules or executing experiment code.

## First Future Fixture Candidates

Potential comparable-code-surface fixture:

- input: two code records or versions with explicit authority and capture-state
  facts;
- output: findings over the comparable surface, such as same-observed, changed,
  missing, unverified, redacted, or not-compared;
- first case: one recorded-context comparison or one recorded-to-managed
  comparison;
- later cases: managed-version inventory comparison, snapshot capture-state
  edge cases, editable-folder observation, and materialized-directory
  comparison;
- boundary: no universal diff engine, no semantic source diff, no Git analysis,
  no environment readiness, and no execution.

Potential workspace-materialization-intent fixture:

- input: a selected managed code version plus candidate destination policy;
- output: a materialization plan with destination paths, collision or overwrite
  findings, provenance labels, and skipped, redacted, or unavailable file
  findings;
- boundary: no file writes, no Git UI, no merge model, no dependency install,
  no execution.

Potential workspace-materialization fixture:

- input: a selected managed code version and approved materialization target;
- output: an editable workspace with provenance back to the managed version and
  explicit skipped, redacted, or unavailable file findings;
- boundary: no Git UI, no merge model, no dependency install, no execution.

Potential declared-environment-inventory fixture:

- input: a managed code version plus user-declared environment file,
  lockfile, interpreter, or package-manager references;
- output: declared environment inventory with present, missing, reference-only,
  or not-checked findings;
- boundary: no sync, no import, no hardware readiness, no execution.

Potential environment-readiness fixture:

- input: a managed code version plus a user-declared environment file or
  lockfile reference;
- output: restore/readiness summary that says what would be synced or checked;
- boundary: no hardware import, no notebook execution, no claim that the
  experiment result is reproducible.

All fixtures should keep code execution separate from code record integrity.
