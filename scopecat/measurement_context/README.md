# Measurement Context Engineering Prototype

This module owns narrow measurement-context support surfaces that have moved
from implementation candidates into production-shaped prototype code.

Current promoted surfaces:

```text
explicit measurement records
  -> explicit family-owned context record summaries
  -> explicit resolved or missing optional context links
  -> local context-link review summary
```

The context-link surface summarizes zero, linked, and missing optional context
links for measurement records. It keeps context records family-owned and
reference-only, keeps context optional for primary-data validity, and surfaces
missing optional context as review findings.

```text
explicit current/reference measurement record pair
  -> user-selected reference mark
  -> resolved measurement-record context links
  -> local objective comparison findings
```

The comparison surface compares actual resolved measurement-record context
links for a current measurement and a user-selected reference measurement. It
reports objective changed, same-observed, and missing optional-context findings
without opening context payloads.

The outputs are local `review_summary` / local review projections. They do not
compare measurement intent selectors, primary data, fit quality, context
payloads, readiness, hardware runtime state, cause attribution, recursively
traverse relations, import context, store or mutate context links, write back,
restore behavior, execute code, or define GUI behavior. They also do not
define a shared context schema or relation graph.

The promoted boundaries are owned by
[`../../docs/architecture/measurement-context/context-link-construction-decision.md`](../../docs/architecture/measurement-context/context-link-construction-decision.md)
and
[`../../docs/architecture/measurement-context/resolved-context-link-comparison-decision.md`](../../docs/architecture/measurement-context/resolved-context-link-comparison-decision.md).

## API Surface

Current local surface:

- `MeasurementContextLinkRequest.from_dict(...)`;
- `summarize_measurement_context_links(...)`;
- `MeasurementContextLinkResult.to_dict()`;
- `build_measurement_context_link_summary(...)`;
- `ResolvedContextLinkComparisonRequest.from_dict(...)`;
- `compare_resolved_context_links(...)`;
- `ResolvedContextLinkComparisonResult.to_dict()`;
- `build_resolved_context_link_comparison_summary(...)`.

The typed request/result objects are the route-local engineering objects. The
raw dictionary builder remains only as an edge adapter for fixture parity and
current callers.
