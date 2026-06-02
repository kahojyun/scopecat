# Setup Binding Discovery Track

## Status

Discovery track index; implementation candidate only.

The previous route-local live owner was withdrawn because it mechanically
promoted summary-shaped candidate behavior instead of a workflow-shaped
setup-binding boundary.

## Candidate Boundary

The validated implementation candidate summarizes explicit setup-binding facts:

- redacted station registry context references;
- setup-binding snapshots for sample/cooldown/session-specific logical-to-
  physical binding context;
- declared generated line/readout views;
- measurement run-start input references;
- simple binding diffs and review attention.

The candidate output is local review data. It does not inspect hardware, execute
project generator/converter code, interpret opaque inner payloads, write
parameter state, write setup state, infer wiring ontology, decide parameter
validity, start runs, or define a shared input-snapshot schema.

## Historical Evidence

- [`../../problem-briefs/setup-binding.md`](../../problem-briefs/setup-binding.md)
- [`../../slices/setup-binding/setup-binding-validation-result.md`](../../slices/setup-binding/setup-binding-validation-result.md)
- [`../../../../implementation_candidates/setup_binding/README.md`](../../../../implementation_candidates/setup_binding/README.md)

## Reopen Triggers

Update the active workflow map, capability map, implementation register,
prototype-boundary note, and module README when a branch promotes or changes
any of these boundaries:

- setup-binding storage/read behavior;
- station-registry schema, station management, or connection payload handling;
- generator/converter execution or payload interpretation;
- hardware setup truth or hardware control;
- parameter invalidation/write-back behavior;
- prepared-run, selected-reference, or measurement-context consumption
  semantics;
- GUI/notebook review presentation.
