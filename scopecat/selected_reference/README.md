# Selected Reference Engineering Prototype

This route-local module promotes selected-reference comparison into
production-shaped prototype code.

The accepted boundary is intentionally narrow:

```text
explicit current/reference measurement pair
  -> user-selected reference mark
  -> declared comparison scope
  -> declared context facts
  -> local objective comparison findings
```

The prototype has two side-effect-free comparison surfaces:

- basic context comparison over measurement identity, declared preview
  metadata, named input snapshots, selected context artifacts, and declared
  facts;
- recorded-code context comparison over recorded code context identity, code
  snapshot record identity, included file inventory, and declared context refs.

The output is a local `review_summary` / local review projection. It does not
read raw measurement payloads, compare fit quality, inspect Git state, read
source files, restore workspaces, resolve dependencies, execute code, prove
physical setup truth, decide reference goodness, infer cause, or define a
shared context schema.

The promoted boundary is owned by
[`../../docs/architecture/selected-reference/engineering-prototype-promotion-decision.md`](../../docs/architecture/selected-reference/engineering-prototype-promotion-decision.md).

## API Surface

Current local surface:

- `SelectedReferenceComparisonRequest.from_dict(...)`;
- `compare_selected_reference_context(...)`;
- `SelectedReferenceComparisonResult.to_dict()`;
- `build_selected_reference_context_summary(...)`;
- `SelectedReferenceCodeContextComparisonRequest.from_dict(...)`;
- `compare_selected_reference_code_context(...)`;
- `build_selected_reference_code_context_summary(...)`.

The typed request/result objects are the route-local engineering objects. Raw
dictionary builders remain only as edge adapters for fixture parity and current
callers.
