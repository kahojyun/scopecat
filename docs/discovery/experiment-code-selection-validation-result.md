# Experiment Code Selection Validation Result

## Status

Fixture-level validation result, not an ADR.

This result records what the first experiment-code selection fixture proved and
where the boundary remains intentionally narrow.

## Fixture

- `tests/fixtures/experiment_code_selection/messy_external_capture/`

The fixture validates a first selected-code boundary:

- a messy external code folder can be represented as selected code context;
- Git state can be recorded as observed evidence without becoming product
  authority;
- dirty roots, dirty nested helper repositories, backups, checkpoints, and
  caches can be surfaced as attention or classification state;
- a selected entrypoint can be recorded separately from helper scope;
- a calibration step can reference code context, parameter state, and setup
  binding as separate named inputs;
- generated companions can be linked as observed artifacts without
  regeneration;
- environment and local-service assumptions can be recorded as hints rather
  than environment management;
- mutation-capable or hardware-active code can be marked without granting
  execution permission;
- a captured-version candidate can describe what Scopecat may later manage
  without accepting storage, merge, or workflow semantics.

## Boundary Confirmed

Scopecat can be opinionated about selected-code records before it is
opinionated about user code organization.

The useful first boundary is not "trust Git" or "force a workflow DAG." It is:

- the user-selected external root;
- the user-selected entrypoint;
- included helper scope;
- excluded or classified files;
- observed version evidence;
- generated companions;
- environment hints;
- mutation and hardware-active attention;
- the candidate capture scope for a future Scopecat-managed code version.

This validates the product posture in
[`managed-experiment-code-posture.md`](managed-experiment-code-posture.md):
Scopecat may eventually provide Git-like managed experiment-code versions
behind lab-native actions, but the first fixture is selected context and a
captured-version candidate.

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
- ignore/classification policy may need user-editable rules;
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
workspace storage, Git replacement, environment management, execution, or
workflow/DAG contracts until another slice creates concrete implementation
pressure.
