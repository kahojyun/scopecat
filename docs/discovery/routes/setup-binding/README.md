# Setup Binding Route

## Status

Promoted narrow engineering prototype.

Setup binding now has a route-local live owner for side-effect-free summary
and review projection:

- [`../../../../scopecat/setup_binding/README.md`](../../../../scopecat/setup_binding/README.md)
- [`../../../architecture/setup-binding/engineering-prototype-promotion-decision.md`](../../../architecture/setup-binding/engineering-prototype-promotion-decision.md)

Artifact posture: `internal_validation_summary`.

This route note coordinates discovery evidence and live engineering posture. It
is not public documentation, a final station-registry schema, a hardware-control
contract, or a shared run-context model.

## Promoted Boundary

The accepted engineering prototype summarizes explicit setup-binding facts:

- redacted station registry context references;
- setup-binding snapshots for sample/cooldown/session-specific logical-to-
  physical binding context;
- declared generated line/readout views;
- measurement run-start input references;
- simple binding diffs and review attention.

The promoted output is local review data. It does not inspect hardware, execute
project generator/converter code, interpret opaque inner payloads, write
parameter state, write setup state, infer wiring ontology, decide parameter
validity, start runs, or define a shared input-snapshot schema.

## Historical Evidence

- [`../../problem-briefs/setup-binding.md`](../../problem-briefs/setup-binding.md)
- [`../../slices/setup-binding/setup-binding-validation-result.md`](../../slices/setup-binding/setup-binding-validation-result.md)
- [`../../../../implementation_candidates/setup_binding/README.md`](../../../../implementation_candidates/setup_binding/README.md)

## Reopen Triggers

Update this route and the promotion map when a branch changes any of these
boundaries:

- setup-binding storage/read behavior;
- station-registry schema, station management, or connection payload handling;
- generator/converter execution or payload interpretation;
- hardware setup truth or hardware control;
- parameter invalidation/write-back behavior;
- prepared-run, selected-reference, or measurement-context consumption
  semantics;
- GUI/notebook review presentation.
