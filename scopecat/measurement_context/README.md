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
explicit supporting-evidence manifest
  -> user-supplied evidence reference
  -> declared related targets
  -> local supporting-evidence review summary
```

The supporting-evidence surface summarizes explicit debug, audit, handoff, or
review-evidence references. It keeps `attachment`, `artifact`, and
`unspecified` as label-only evidence kinds, requires explicit lifecycle
posture, and surfaces unavailable evidence or target references as review
findings.

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
import supporting-evidence payloads, observe files, validate checksums,
validate artifact provenance, restore behavior, execute code, or define GUI
behavior. They also do not define a shared context schema, relation graph, or
attachment schema.

The promoted boundaries are owned by
[`../../docs/architecture/measurement-context/context-link-construction-decision.md`](../../docs/architecture/measurement-context/context-link-construction-decision.md)
,
[`../../docs/architecture/measurement-context/supporting-evidence-reference-decision.md`](../../docs/architecture/measurement-context/supporting-evidence-reference-decision.md),
and
[`../../docs/architecture/measurement-context/resolved-context-link-comparison-decision.md`](../../docs/architecture/measurement-context/resolved-context-link-comparison-decision.md).

## API Surface

Current local surface:

- `MeasurementContextLinkRequest.from_dict(...)`;
- `summarize_measurement_context_links(...)`;
- `MeasurementContextLinkResult.to_dict()`;
- `build_measurement_context_link_summary(...)`;
- `SupportingEvidenceReferenceRequest.from_dict(...)`;
- `summarize_supporting_evidence_reference(...)`;
- `SupportingEvidenceReferenceResult.to_dict()`;
- `build_supporting_evidence_reference_summary(...)`;
- `ResolvedContextLinkComparisonRequest.from_dict(...)`;
- `compare_resolved_context_links(...)`;
- `ResolvedContextLinkComparisonResult.to_dict()`;
- `build_resolved_context_link_comparison_summary(...)`.

The typed request/result objects are the route-local engineering objects. The
raw dictionary builder remains only as an edge adapter for fixture parity and
current callers.
