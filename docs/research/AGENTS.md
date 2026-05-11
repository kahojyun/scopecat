# Research Agent Instructions

- Treat files in this directory as evidence inputs unless they explicitly say
  they are extracted, promoted, or accepted.
- Prefer extracted notes and `research-index.md` over raw notes when they
  exist.
- Do not infer current product direction directly from raw research.
- When adding a research note, include `Status`, `Source`, `Summary`,
  `Extracted To`, and `Remaining Value`.
- For user interview summaries, include participant context, journey evidence,
  pain evidence, adoption signals, and redaction notes.
- Track extraction progress in the note itself; create or update
  `research-index.md` when there are enough research files that status is hard
  to see locally.
- Promote durable conclusions out of `research/` into the narrowest justified
  project doc. Do not leave accepted product or architecture truth only in raw
  research.
- After extraction or supersession, prefer deleting low-value research notes
  over keeping them indefinitely. Use `archived/` only when there is clear
  provenance, audit, citation, or rejection-rationale value.
- Do not create lifecycle folders, taxonomy folders, or placeholder files
  before there is real content for them.
- Use normal Markdown links and indexes. Do not rely on Obsidian-only,
  Foam-only, or backlink-only navigation.
- Keep public-docs redaction in mind. Do not add sensitive identity details or
  unredacted private interview material without a clear internal need.
