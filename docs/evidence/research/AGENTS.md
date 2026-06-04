# Research Agent Instructions

- Treat files in this directory as evidence inputs unless a current Scopecat
  wrapper, index, or promoted doc explicitly says the claim has been extracted,
  promoted, or accepted.
- Imported source snapshots may contain source-local statuses such as
  "Accepted"; those statuses do not count as current Scopecat acceptance.
- Prefer extracted notes and `research-index.md` over raw notes when they
  exist.
- Do not infer current product direction directly from raw research.
- When adding a research note, include `Status`, `Source`, `Summary`,
  `Current Use`, and `Remaining Value`.
- For user interview summaries, include participant context, scenario evidence,
  pain evidence, adoption signals, and portability/public-redaction notes where
  relevant.
- Track extraction progress in the note itself; create or update
  `research-index.md` when there are enough research files that status is hard
  to see locally.
- Promote durable conclusions out of `research/` into the narrowest justified
  project doc. Do not leave accepted product or architecture truth only in raw
  research.
- Promote cross-option evidence interpretation, source-confidence rules, or
  prompt-method rules to `docs/evidence/method.md`; keep
  `docs/evidence/evidence-register.md` focused on rows and stable IDs.
- Promote problem framing to `docs/discovery/problem-briefs/` and product
  adoption changes or adoption-route evidence to
  `docs/product/adoption-strategy.md`.
- After extraction or supersession, prefer deleting low-value research notes
  over keeping them indefinitely. Before deleting a source that supports active
  `EV`, decision, validation, or architecture work, leave a compact extracted
  note, source map, or evidence anchor in the current owner. Use `archived/`
  only when there is clear provenance, audit, citation, or rejection-rationale
  value.
- Do not create lifecycle folders, taxonomy folders, or placeholder files
  before there is real content for them.
- Use normal Markdown links and indexes. Do not rely on Obsidian-only,
  Foam-only, or backlink-only navigation.
- Keep public-docs redaction in mind. Do not add sensitive identity details or
  unredacted private interview material without a clear internal need, and do
  not treat this documentation rule as product evidence by itself.
