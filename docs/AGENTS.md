# Documentation Agent Instructions

- Treat `docs/` as durable project memory. Do not add placeholder structure
  before there is durable content.
- Keep public-facing documentation under `docs/user/` when it is introduced.
- Treat `docs/user/` as publishable and redacted by default.
- Keep internal product, architecture, research, decision, and AI-assistive
  material out of user documentation unless it is intentionally promoted.
- Prefer one owning document per durable fact. Cross-link instead of
  duplicating, and make accepted decisions, validation scope, contracts,
  hypotheses, and open questions easy to distinguish.
- Keep cross-references purposeful: use them for entry points, owner
  boundaries, required dependencies, or source evidence. Avoid repeated
  historical back-links when a README or index already owns the navigation.
- Keep trackers compact: status, current decision points, links, and short
  cross-document coordination notes. Do not use trackers as journey-local task
  queues. Move durable detail into narrower owner docs once it has multiple
  active consumers.
- Do not copy an existing journey folder structure unless the new journey has
  earned the same artifact types.
