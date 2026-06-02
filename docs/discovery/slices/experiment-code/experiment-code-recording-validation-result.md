# Experiment Code Recording Validation Result

## Status

Fixture validation result with code recording summary candidate, not an ADR.

This result records what the first experiment-code recording fixture proved and
where the boundary remains intentionally narrow.

## Fixture

- `tests/fixtures/experiment_code_recording/basic_step_code_record/`
- `implementation_candidates/experiment_code_recording/`

The fixture validates a first code-recording boundary:

- a messy external code folder can be represented as recorded calibration-step
  code context;
- early adoption can use minimal explicit include recording rather than
  record-all folder tracking;
- internal Git state can be ignored rather than analyzed;
- unrecorded files, backups, checkpoints, caches, and generated files do not
  need to become noisy warnings;
- included notebooks can be recorded as source without outputs;
- a recorded entrypoint can be represented separately from included files;
- a calibration step can reference code context, parameter state, and setup
  binding as separate named inputs;
- declared context references, such as environment profile hints, can be linked
  without dependency discovery;
- mutation capability can remain not analyzed, and recording still does not
  grant execution permission;
- a code snapshot record can describe the included scope and capture posture
  that Scopecat may later manage without accepting storage, restore, sync,
  environment, saved-version selection or loading, execution, merge, or
  workflow semantics.

## Boundary Confirmed

Scopecat can be opinionated about code snapshot records before it is opinionated
about user code organization.

The useful first boundary is not "trust Git," "force a workflow DAG," or "ask
the user to curate the authoritative code snapshot selection first." It is a
point-in-time code snapshot defined by:

- the recorded external root or source reference;
- the recorded entrypoint;
- the explicit include list or recorded source observations;
- explicit code capture state for included code items, such as content-captured,
  reference-only, missing, redacted, or excluded;
- notebook-output stripping before capture;
- broad non-recording policy for unrecorded files;
- declared context references;
- no internal Git inspection;
- no dependency discovery, import, execution, or mutation analysis;
- the code snapshot record scope for a future Scopecat-managed code version.

Recording is the first adoption action. Selection can later choose, promote, or
restore one of these records, but the durable product pressure starts with the
code snapshot record associated with a run or step. That record should
be comparable to parameter-state and setup-binding snapshots while still
keeping code-specific storage, restore, and execution semantics separate.

This validates the product strategy in
[`policies/managed-experiment-code-posture.md`](../../policies/managed-experiment-code-posture.md):
Scopecat may eventually provide Git-like managed experiment-code versions
behind lab-native actions, but the first fixture is a recorded code context
that defines a code snapshot record with minimal explicit include recording.

## Adoption Route Covered

The fixture covers the first adoption stage for code recording:

- users record the files and references associated with a calibration step
  instead of asking Scopecat to understand the whole legacy codebase;
- Scopecat records that context as the scope of a point-in-time code snapshot
  connected to calibration intent;
- notebook capture is useful immediately because outputs can be stripped while
  preserving source;
- unrecorded files remain outside the record unless the user adds them;
- included items may still differ in code capture state, and reference-only items
  should not be presented as content-comparable;
- the code snapshot record leaves room for later Scopecat-managed
  workspaces without pretending that storage, restore, or execution contracts
  already exist.

From the perspective of this first code-recording fixture, the deferred
validation chain starts with promoting captured snapshots into managed code
versions, then comparing explicit code fact surfaces, planning workspace
materialization, creating editable workspaces, observing editable folders
against selected managed versions, preparing run context from selected code and
other run-start inputs, preparing a manual rerun from selected-reference
context, recording declared environment inventory, and only later syncing a
declared environment such as a `uv` lockfile workflow.

That sequence is historical to this first fixture, not an active sequencing
recommendation. Active sequencing should live in the implementation or PR
plan. The validation order is also not a required user adoption route.
These are plausible long-term capabilities, not conclusions earned by this
fixture. Selecting a saved code snapshot for a step is not useful enough as a
standalone validation question unless it reduces a concrete run-preparation or
rerun risk.

## Relationship To Prior Slices

The fixture reuses validated pressure without promoting shared architecture:

- parameter-state management contributes selected parameter-state context;
- setup binding contributes selected setup-binding context;
- selected-reference comparison contributes declared recorded-code context
  comparison pressure;
- selected measurement export contributes handoff and materialization pressure;
- calibration continuation contributes step-level context references.

The fixture uses named inputs because that vocabulary is useful, but it does
not earn a shared run-context, step-context, or snapshot framework.

## Summary Candidate

The implementation candidate checks that the current code snapshot record can be
produced mechanically from explicit fixture input without adding
folder, Git, dependency, environment, or execution authority.

It assembles and validates:

- recorded external roots;
- recorded code contexts with entrypoint, include list, declared refs, and
  mutation-capability classification;
- included file summaries;
- non-recording policy for unrecorded files;
- calibration-step references to recorded code context;
- code snapshot record scope;
- attention items for stripped notebooks, unrecorded explicitly excluded files,
  ignored Git state, and no execution permission.

The builder remains side-effect free. It does not read source files, inspect
Git state, scan unrecorded folders, discover dependencies, import code,
execute code, restore environments, materialize workspaces, or define
workflow/DAG contracts.

The candidate does not prove product usefulness by itself. It shows that the
fixture's recorded code context can define a coherent code snapshot summary
with basic referential integrity checks while keeping managed workspace storage
and environment restoration deferred.

## Remaining Risks

- the final managed workspace store is still undecided;
- capture-state vocabulary still needs comparison fixtures before becoming a
  shared contract;
- the first content-integrity mechanism is still undecided: archive, checksums,
  file snapshot, content-addressed store, or Git-backed implementation;
- include-list helper UX and user-editable recording policy remain undecided;
- internal Git diagnostics may become useful later, but they are intentionally
  absent from the first adoption boundary;
- environment readiness may need a later active validation slice;
- generated companion handling may need a separate transformation or build
  pipeline slice;
- workflow/DAG nodes may become valuable for stable calibration routines, but
  their inputs, outputs, compatibility, and review contracts are not earned;
- GUI language for save/restore/compare/use-version actions remains undecided.

## Slice Recommendation

Use this fixture and summary candidate as the first boundary for
experiment-code recording. It supports the deferred route described in
[`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md):
do not design managed workspace storage, Git replacement, internal Git
analysis, record-all file tracking, environment management, execution, or
workflow/DAG contracts until another slice creates concrete implementation
pressure.
