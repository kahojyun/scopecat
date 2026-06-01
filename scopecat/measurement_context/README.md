# Measurement Context Engineering Prototype

This module owns narrow measurement-context support surfaces that have moved
from implementation candidates into production-shaped prototype code.

Current promoted surface:

```text
explicit current/reference measurement record pair
  -> user-selected reference mark
  -> resolved measurement-record context links
  -> local objective comparison findings
```

The first accepted surface compares actual resolved measurement-record context
links for a current measurement and a user-selected reference measurement. It
reports objective changed, same-observed, and missing optional-context findings
without opening context payloads.

The output is a local `review_summary` / local review projection. It does not
compare measurement intent selectors, primary data, fit quality, context
payloads, readiness, hardware runtime state, cause attribution, recursive
relations, context import, write-back, restore behavior, execution, or GUI
behavior. It also does not define a shared context schema or relation graph.

The promoted boundary is owned by
[`../../docs/architecture/measurement-context/resolved-context-link-comparison-decision.md`](../../docs/architecture/measurement-context/resolved-context-link-comparison-decision.md).

## API Surface

Current local surface:

- `ResolvedContextLinkComparisonRequest.from_dict(...)`;
- `compare_resolved_context_links(...)`;
- `ResolvedContextLinkComparisonResult.to_dict()`;
- `build_resolved_context_link_comparison_summary(...)`.

The typed request/result objects are the route-local engineering objects. The
raw dictionary builder remains only as an edge adapter for fixture parity and
current callers.
