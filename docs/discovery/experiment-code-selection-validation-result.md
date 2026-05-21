# Experiment Code Selection Validation Result

## Status

Fixture-level validation result, not an ADR.

This result records what the first experiment-code selection fixture proved and
where the boundary remains intentionally narrow.

## Fixture

- `tests/fixtures/experiment_code_selection/messy_external_capture/`

The fixture validates a first selected-code boundary:

- a messy external code folder can be represented as selected code context;
- early adoption can use minimal whitelist capture rather than record-all
  folder tracking;
- internal Git state can be ignored rather than analyzed;
- unselected files, backups, checkpoints, caches, and generated files do not
  need to become noisy warnings;
- whitelisted notebooks can be recorded as source without outputs;
- a selected entrypoint can be recorded separately from whitelisted files;
- a calibration step can reference code context, parameter state, and setup
  binding as separate named inputs;
- declared context references, such as environment profile hints, can be linked
  without dependency discovery;
- mutation capability can remain not analyzed, and selection still does not
  grant execution permission;
- a captured-version candidate can describe what Scopecat may later manage
  without accepting storage, merge, or workflow semantics.

## Boundary Confirmed

Scopecat can be opinionated about selected-code records before it is
opinionated about user code organization.

The useful first boundary is not "trust Git" or "force a workflow DAG." It is:

- the user-selected external root;
- the user-selected entrypoint;
- the user-whitelisted file list;
- notebook-output stripping before capture;
- broad non-recording policy for unwhitelisted files;
- declared context references;
- no internal Git inspection;
- no dependency discovery, import, execution, or mutation analysis;
- the candidate capture scope for a future Scopecat-managed code version.

This validates the product posture in
[`managed-experiment-code-posture.md`](managed-experiment-code-posture.md):
Scopecat may eventually provide Git-like managed experiment-code versions
behind lab-native actions, but the first fixture is selected context and a
captured-version candidate with minimal whitelist capture.

## Adoption Route Covered

The fixture covers the first adoption stage for code selection:

- users choose the files and references that matter to the experiment instead
  of asking Scopecat to understand the whole legacy codebase;
- Scopecat records those choices as experiment code context connected to
  calibration and measurement intent;
- notebook capture is useful immediately because outputs can be stripped while
  preserving source;
- unselected files remain outside the record unless the user adds them;
- the captured-version candidate leaves room for later Scopecat-managed
  workspaces without pretending that storage, restore, or execution contracts
  already exist.

The next stages are intentionally deferred: moving users into managed
workspaces, restoring a selected code version, comparing managed versions,
loading code for a run, and syncing a declared environment such as a `uv`
lockfile workflow. Those are plausible long-term capabilities, not conclusions
earned by this fixture.

## Relationship To Prior Slices

The fixture reuses validated pressure without promoting shared architecture:

- parameter-state management contributes selected parameter-state context;
- setup binding contributes selected setup-binding context;
- selected-reference comparison contributes the need for future code-version
  comparison;
- selected measurement export contributes handoff and materialization pressure;
- calibration continuation contributes step-level context references.

The fixture uses named inputs because that vocabulary is useful, but it does
not earn a shared run-context, step-context, or snapshot framework.

## Remaining Risks

- the final managed workspace store is still undecided;
- the first content-integrity record is still undecided: archive, checksums,
  file snapshot, content-addressed store, or Git-backed implementation;
- whitelist helper UX and user-editable capture policy remain undecided;
- internal Git diagnostics may become useful later, but they are intentionally
  absent from the first adoption boundary;
- environment readiness may need a later active validation slice;
- generated companion handling may need a separate transformation or build
  pipeline slice;
- workflow/DAG nodes may become valuable for stable calibration routines, but
  their inputs, outputs, compatibility, and review contracts are not earned;
- GUI language for save/restore/compare/use-version actions remains undecided.

## Current Recommendation

Use this fixture as the first boundary for experiment-code selection. The next
implementation-shaped step, if needed, should be a pure summary candidate that
turns selected code context into expected review output. Do not design managed
workspace storage, Git replacement, internal Git analysis, record-all file
tracking, environment management, execution, or workflow/DAG contracts until
another slice creates concrete implementation pressure.
