# Experiment Code Discovery Track

## Status

Discovery track index; implementation candidates only.

There is no live experiment-code implementation owner. The previous promoted
module was withdrawn because candidate-summary parity was doing too much
architectural work. Future work should promote a workflow-shaped boundary
around a concrete user step rather than revive the slice catalog.

## Discovery Conclusion

The validated experiment-code chain is useful as evidence:

```text
record -> promote -> materialize -> observe -> prepare
```

It describes adjacent responsibilities around recorded code context, code
snapshot records, managed code versions, workspace materialization, editable
folder observation, prepared-run context, and reference-based rerun
preparation. This chain is not mandatory for every measurement and is not a
live workflow owner.

Measurement records remain the user-facing evidence and selection anchor.
Experiment code is one linked context family for a measurement, run, step,
calibration, comparison, or handoff. Prepared-run context is a local review
composition surface; it does not decide runnable readiness or execution.

## Carry Forward

Keep these concepts available if the route reopens:

- code context tied to a run or step;
- explicit include policy and capture-state vocabulary;
- code snapshot record and managed code version identity;
- declared inventory and integrity hints;
- side-effect-free materialization intent before approved writes;
- no-overwrite workspace materialization under caller-provided roots;
- read-only editable-folder observation against selected managed inventory;
- prepared-run context as review composition, not execution authority.

## Not Earned

Do not infer these from current discovery evidence:

- final managed workspace storage or content-addressed backend;
- Git replacement behavior, branch/merge/sync semantics, or Git diagnostics;
- default record-all folder tracking;
- semantic source diff or generated-artifact regeneration;
- code import, loading, notebook execution, or managed run execution;
- environment restoration or dependency sync;
- hardware control, workflow/DAG ownership, or shared run-context schema;
- GUI save/restore/use-version behavior.

## Historical Evidence

Use the compact slice inventory and problem/policy owners instead of rebuilding
the old route map:

- [`../../archive/slice-inventory.md`](../../archive/slice-inventory.md)
- [`../../problem-briefs/experiment-code-recording.md`](../../problem-briefs/experiment-code-recording.md)
- [`../../policies/managed-experiment-code-posture.md`](../../policies/managed-experiment-code-posture.md)

Environment-operation evidence remains owned separately:

- [`../environment-operation/README.md`](../environment-operation/README.md)
- [`../../../engineering/prototype-boundaries/environment-operation.md`](../../../engineering/prototype-boundaries/environment-operation.md)

## Reopen Triggers

Reopen this route only around a named product or engineering question:

- handoff needs reference-only experiment context package projection;
- users need code loading/execution authority;
- managed storage needs one concrete backend decision;
- comparison needs stronger managed-version inventory or capture-state
  evidence;
- prepared-run work needs a workflow-shaped route boundary.

Do not add another experiment-code slice merely to restate recording,
managed-version identity, materialization planning, editable observation, or
prepared-run context.
