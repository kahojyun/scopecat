# Research

## Status

Stable research workspace policy.

## Purpose

`docs/evidence/research/` stores evidence inputs and extracted research notes:
interview summaries, external reference notes, legacy codebase observations,
and technical spike notes.

Research is input, not product truth. Durable conclusions should move to the
smallest owning document outside `research/`.

## Knowledge Base Rules

- Raw notes may be messy, partial, and contradictory.
- Extracted notes should summarize reusable claims and separate facts from
  interpretation.
- Future sessions should read [`research-index.md`](research-index.md) and
  extracted notes before raw notes.
- Use normal Markdown links and indexes; do not rely on editor-specific
  backlink systems.
- Do not store sensitive identity details or unredacted private material unless
  there is a clear internal need.

## Note Shape

Research notes should normally include:

```markdown
## Status
## Source
## Summary
## Current Use
## Remaining Value
```

User interview summaries should also capture participant context, scenario or
pain evidence, adoption signals, and redaction notes when relevant.

## Status Values

| Status | Meaning |
| --- | --- |
| Raw | Captured input; not yet triaged. |
| Triaged | Read once; main possible value is known. |
| Extracting | Claims are being pulled into extracted notes or durable docs. |
| Extracted | Important content has been promoted or summarized elsewhere. |
| Quarantined | Preserved for evidence, pressure, vocabulary, or provenance but not accepted as product scope. |
| Superseded | Replaced by newer research, summary, or decision. |
| Archived | Kept for provenance; should not normally be consulted. |

## Promotion Targets

- evidence claims -> [`../evidence-register.md`](../evidence-register.md)
- evidence interpretation, source coverage, and bias rules -> [`../method.md`](../method.md)
- problem framing -> [`../../discovery/problem-briefs/`](../../discovery/problem-briefs)
- product adoption strategy -> [`../../product/adoption-strategy.md`](../../product/adoption-strategy.md)
- adoption-route evidence -> [`../../product/adoption-strategy.md`](../../product/adoption-strategy.md)
- product direction and boundaries -> [`../../product/direction.md`](../../product/direction.md)

Create validation, decision, architecture, or user docs only when there is a
specific durable owner and content for them.

## Retention

Git history is the fallback for low-value research provenance. Do not keep
research files in the working tree merely because they once existed.

After a note reaches `Extracted` or `Superseded`, choose one outcome:

- delete it when useful content has been promoted and remaining value is low;
- archive it when it still has clear provenance, audit, citation, or rejection
  rationale value;
- keep it active only when additional extraction work remains.
