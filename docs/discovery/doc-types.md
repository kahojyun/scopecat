# Discovery Document Types

## Status

Discovery documentation convention.

Discovery docs intentionally preserve problem framing, validation evidence, and
deferred decisions before engineering or production owners accept a boundary.
Use the narrowest document type that owns the statement being made.

## Types

| Type | Location | Responsibility |
| --- | --- | --- |
| Entry point | [`README.md`](README.md) | Short navigation, current document organization, and links to route/slice owners. |
| Problem brief | [`problem-briefs/`](problem-briefs/) | Evidence-backed user problem framing before choosing a validation question. |
| Policy or boundary | [`policies/`](policies/) | Cross-route vocabulary, artifact boundaries, artifact classification, or product-boundary vocabulary that multiple slices should reference. |
| Discovery track index | [`routes/`](routes/) | Discovery-track navigation, discovery status, and track-specific validation pointers. The directory name is a legacy path. |
| Discovery track decision | [`routes/`](routes/) | Accepted-for-now discovery decisions, deferred decisions, reopen triggers, and stop rules. |
| Slice plan | [`slices/`](slices/) | Pre-implementation validation intent for one narrow slice. |
| Slice validation result | [`slices/`](slices/) | What one fixture or implementation candidate earned and explicitly did not earn. |
| Slice evidence entry | [`slices/README.md`](slices/README.md) | How to use validation results as evidence without treating the old inventory as a roadmap. |
| Synthesis | [`synthesis/`](synthesis/) | Cross-slice recurring concepts, deferrals, and comparison pressure. |

## Ownership Rules

- Prefer discovery-track decisions for discovery sequencing and stop rules.
  Once a track has live engineering ownership, prefer
  [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
  for workflow sequencing and
  [`../product/target-capabilities.md`](../product/target-capabilities.md)
  for capability maturity. Use
  [`../engineering/implementation-register.md`](../engineering/implementation-register.md)
  for implementation ownership.
- A track `README.md` may temporarily own consolidation and recommended next
  work when a track has not yet earned a separate decision document; split it
  once decisions, reopen triggers, or stop rules need a stable owner.
- Prefer slice validation results for evidence about a specific fixture or
  implementation candidate.
- Prefer policies for repeated boundary vocabulary.
- Prefer synthesis for cross-route vocabulary that is not yet accepted
  architecture.
- Do not promote slice-local vocabulary into shared product contracts merely
  because two documents use similar words.
- Do not rewrite old validation results just because later track documents
  supersede their sequencing guidance; link to the newer owner instead.
