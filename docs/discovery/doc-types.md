# Discovery Document Types

## Status

Documentation convention, not an ADR.

Discovery docs intentionally preserve problem framing, validation evidence, and
deferred decisions before architecture is accepted. Use the narrowest document
type that owns the statement being made.

## Types

| Type | Location | Responsibility |
| --- | --- | --- |
| Entry point | [`README.md`](README.md) | Short navigation, current document organization, and links to route/slice owners. |
| Problem brief | [`problem-briefs/`](problem-briefs/) | Evidence-backed user problem framing before choosing a validation question. |
| Policy or boundary | [`policies/`](policies/) | Cross-route vocabulary, artifact boundaries, or product posture that multiple slices should reference. |
| Route index | [`routes/`](routes/) | Route navigation, current posture, and route-specific next-work pointers. |
| Route decision | [`routes/`](routes/) | Accepted-for-now route decisions, deferred decisions, reopen triggers, and stop rules. |
| Slice plan | [`slices/`](slices/) | Pre-implementation validation intent for one narrow slice. |
| Slice validation result | [`slices/`](slices/) | What one fixture or implementation candidate earned and explicitly did not earn. |
| Slice inventory | [`slices/README.md`](slices/README.md) | Current maturity list for validated slices. |
| Synthesis | [`synthesis/`](synthesis/) | Cross-slice recurring concepts, deferrals, and comparison pressure. |

## Ownership Rules

- Prefer route decisions for sequencing and stop rules.
- A route `README.md` may temporarily own consolidation and recommended next
  work when a route has not yet earned a separate decision document; split it
  once decisions, reopen triggers, or stop rules need a stable owner.
- Prefer slice validation results for evidence about a specific fixture or
  implementation candidate.
- Prefer policies for repeated boundary vocabulary.
- Prefer synthesis for cross-route vocabulary that is not yet accepted
  architecture.
- Do not promote slice-local vocabulary into shared product contracts merely
  because two documents use similar words.
- Do not rewrite old validation results just because later route documents
  supersede their sequencing guidance; link to the newer route owner instead.
