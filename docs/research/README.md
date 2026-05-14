# Research

## Status

Stable research workspace policy.

## Purpose

`docs/research/` is the evidence intake and extraction workspace. It stores
raw or semi-processed inputs such as user interview summaries, external
reference notes, legacy codebase observations, and technical spike notes.

Research is not product truth and not architecture truth. It is managed as a
lightweight knowledge base with an explicit promotion workflow:

```text
raw input -> extracted claim -> promoted durable doc
```

## Knowledge Base Rules

- Raw notes are source-like inputs. They may be messy, partial, and
  contradictory.
- Extracted notes are curated reusable summaries. They should link back to
  sources and separate facts from interpretation.
- Promoted docs live outside `research/` and own durable project meaning.
- Future AI sessions should read indexes and extracted notes before raw notes.
- Do not rely on Obsidian-only, Foam-only, or backlink-only navigation. Use
  normal Markdown links and indexes that work in plain editors, GitHub, MkDocs,
  and AI sessions.

## Lifecycle Structure

Create lifecycle folders only when there is content for them:

```text
docs/research/
  research-index.md

  raw/
    interviews/
    legacy-codebase/
    external-references/

  extracted/

  archived/
```

Meanings:

- `raw/` contains source-like inputs, including user interview summaries.
- `extracted/` contains compact, reusable research outputs that are safe entry
  points for future work.
- `archived/` contains exceptional retained provenance that should not normally
  guide future analysis.
- `research-index.md` tracks extraction state once there is more than a small
  handful of research files.

Do not create these folders as placeholders. A flat `research/` directory is
acceptable while there are only a few files.

## Status Values

Every research note should declare one status:

| Status | Meaning |
| --- | --- |
| Raw | Captured input; not yet triaged. |
| Triaged | Read once; main possible value is known. |
| Extracting | Claims are being pulled into extracted notes or durable docs. |
| Extracted | Important content has been promoted or summarized elsewhere. |
| Transitional | Extracted or summarized material kept temporarily until W2 or a later owner doc absorbs the remaining useful claims. |
| Quarantined | Preserved for evidence, pressure, vocabulary, or provenance, but explicitly not accepted as product plan, scope, or architecture. |
| Superseded | Replaced by newer research, summary, or decision. |
| Archived | Kept for provenance; should not normally be consulted. |

`Extracted` means future work should use the linked extracted or promoted
artifact first. After extraction, decide whether the source should remain in
the working tree, move to `archived/`, or be deleted.

Statuses inside imported source snapshots are source-local. They do not imply
current Scopecat acceptance unless a current Scopecat wrapper, index, extracted
note, or promoted durable doc explicitly says so.

## Required Fields

Each research note should include:

```markdown
## Status

## Source

## Summary

## Current Use

## Remaining Value
```

For user interview summaries, also include:

```markdown
## Participant Context

## Journey Evidence

## Pain Evidence

## Adoption Signals

## Redaction Notes
```

Do not store sensitive identity details or unredacted private material unless
there is a clear internal need.

## Promotion Targets

Durable conclusions should be promoted along the current docs model:

```text
Evidence -> User Journey -> Pain Point -> Product Capability
  -> Domain Concept -> Architecture Contract -> Subsystem Spec
```

Use the narrowest durable destination that exists or is justified by real
content:

- repeated pain points -> `product/`
- end-to-end workflows -> `journeys/`
- capability adoption or hypotheses -> `capabilities/`
- stable domain vocabulary -> `concepts/`
- ownership, dependency, or integration contracts -> `architecture/`
- accepted or rejected decisions -> `decisions/`
- public-facing material -> future `user/` docs after redaction review

Do not create placeholder directories just to match this taxonomy.

## Extraction Tracking

When research grows beyond a few files, create `research-index.md` with:

```text
Research item
Source type
Status
Main value
Extracted to
Remaining extraction work
Last reviewed
```

The index should make it clear which raw inputs are still worth reading and
which ones have already been distilled.

## Retention And Cleanup

Git history is the long-term fallback for low-value research provenance. Do
not keep extracted research files in the working tree merely because they once
existed.

After a research note reaches `Extracted` or `Superseded`, choose one outcome:

- delete it when useful content has been promoted and remaining value is low;
- archive it when it still has clear provenance, audit, citation, or rejection
  rationale value;
- keep it active only when additional extraction work remains.

Delete by default when:

- `Extracted To` covers the useful content;
- `Remaining Value` is empty, low, or limited to historical curiosity;
- keeping the note would confuse future AI sessions;
- Git history is enough if someone needs to recover the old text.

Archive only when:

- the source may need later audit or citation;
- it preserves context for why a direction was rejected;
- deleting it would make a promoted decision hard to understand.

`archived/` is not a default destination for old notes. It is for retained
provenance with a clear reason.
