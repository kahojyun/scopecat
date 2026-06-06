# Managed Experiment-Code Posture

## Status

Product strategy note.

This note records the intended product posture for experiment-code management.
Product success signals live in [`success-metrics.md`](success-metrics.md).
Canonical journey and capability relationships live in
[`target-journeys.md`](target-journeys.md) and
[`target-capabilities.md`](target-capabilities.md).

## Direction

Scopecat should eventually manage experiment-code workspaces with Git-like
versioning hidden behind lab-native actions.

The user-facing model should be closer to:

- save this code version;
- restore or materialize this version;
- compare these changes;
- mark this version as useful for a lab purpose;
- use this version for a measurement, calibration step, analysis, or handoff;
- run or inspect readiness under an environment profile when execution support
  is earned.

It should not require ordinary lab users to understand Git commit, branch,
merge, push, pull, rebase, stash, or submodule workflows before Scopecat can
record useful code context.

## Current Boundary

Git and directory structure should not be early-adoption authority.

Many existing lab folders may have stale commits, dirty working trees, nested
repositories, backup folders, notebook checkpoints, copied helper packages,
generated files, and unclear entrypoints. Scopecat should be able to record
useful run or step code context without pretending the folder is well managed.

The first useful boundary is explicit code-context recording:

- record only files or references the user explicitly includes;
- strip notebook outputs before recording `.ipynb` files;
- keep unrecorded backup, cache, checkpoint, and generated files out of scope;
- record root/source reference, entrypoint, include policy, notebook policy,
  and explicit links to measurement, calibration, environment, or setup
  context;
- defer Git inspection, dependency discovery, import-time inspection, runtime
  probes, execution readiness, and mutation-capability inference.

This keeps `recorded` on the audit side. A later active path can choose a code
snapshot or managed code version, materialize it into a workspace, and then
record which code context was actually associated with the run or step.

## Long-Term Direction

The long-term direction remains managed experiment code, not permanent
record-only capture:

- Scopecat-managed code workspaces can be expanded into editable folders;
- user edits happen in ordinary files and notebooks;
- Scopecat records saved versions and diffs;
- measurements, calibration steps, handoff packages, and rerun preparation can
  reference recorded code context;
- code snapshot records can be materialized on another machine or environment
  when storage and environment support are earned;
- modern-manifest dependency sync, such as a `uv` lockfile workflow, can become
  execution-readiness support only after managed workspace and environment
  authority are accepted.

## Separations To Preserve

Code version should remain separate from:

- parameter state;
- setup binding;
- station registry;
- environment profile;
- Measurement Record;
- selected reference;
- export package;
- generated companion artifact;
- runtime execution or hardware-control authority.

A measurement may reference several of these as named input or context records
at run start. That does not make them one shared version-control model.

## Non-Claims

The current posture does not accept:

- record-all behavior for messy code folders;
- Git state as the primary early-adoption identity;
- package management, deployment, or dependency closure;
- managed runners, remote execution, or hardware-control support;
- workflow/DAG nodes as first-class records;
- regeneration of circuit JSON, chip/line info, registry views, waveform
  adjacent state, or derived analysis arrays;
- environment restoration or lockfile sync for legacy/lab-managed facts.

## Reopen Conditions

Revisit this posture when a named workflow needs one of these boundaries:

- stable code snapshot storage and restore;
- comparable code surfaces or materialized workspaces;
- editable-folder observation;
- execution-readiness or dependency-sync checks;
- managed runners;
- workflow/DAG nodes with stable inputs, outputs, review gates, and
  compatibility expectations.

Historical evidence and hypotheses remain in
[`../discovery/problem-briefs/experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md).
