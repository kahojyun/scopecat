# Setup Binding Engineering Prototype

This route-local module promotes setup-binding context into
production-shaped prototype code.

The accepted boundary is intentionally narrow:

```text
explicit station registry context
  -> explicit setup-binding snapshots
  -> declared generated line/readout views
  -> measurement run-start input references
  -> local review summary and attention findings
```

The prototype has one side-effect-free surface for setup-binding review. It
validates declared fixture facts, summarizes selected/prior binding snapshots,
keeps user/project-defined inner payloads opaque, and records attention-worthy
binding changes without deciding parameter validity.

The output is a local `review_summary` / local review projection. It does not
own station-registry truth, inspect hardware, execute project generator or
converter code, interpret opaque project payloads, mutate parameter state,
write hardware setup, infer wiring ontology, start runs, or define a shared
input-snapshot schema.

The promoted boundary is owned by
[`../../docs/architecture/setup-binding/engineering-prototype-promotion-decision.md`](../../docs/architecture/setup-binding/engineering-prototype-promotion-decision.md).

## API Surface

Current local surface:

- `SetupBindingSummaryRequest.from_dict(...)`;
- `summarize_setup_binding_context(...)`;
- `SetupBindingSummaryResult.to_dict()`;
- `build_setup_binding_summary(...)`.

The typed request/result objects are the route-local engineering objects. The
raw dictionary builder remains only as an edge adapter for fixture parity and
current callers.
