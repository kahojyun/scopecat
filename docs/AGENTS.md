# Documentation Agent Instructions

- Treat `docs/` as durable project memory. Do not add placeholder structure
  before there is durable content.
- Update existing owner documents before creating new structure.
- Keep public-facing documentation under `docs/user/` when it is introduced.
- Treat `docs/user/` as publishable and redacted by default.
- Keep active task queues, priorities, and implementation checklists in issues,
  PRs, or branch-specific working notes when implementation starts rather than
  stable docs landing pages.
- Keep internal product, architecture, research, decision, and AI-assistive
  material out of user documentation unless it is intentionally promoted.
- Prefer one owning document per durable fact once the fact is accepted or
  current. Short-lived duplication is acceptable in branch notes, validation
  drafts, and discovery artifacts while framing is still being tested. Cross-link
  instead of duplicating durable content, and make accepted decisions,
  validation scope, contracts, hypotheses, and open questions easy to
  distinguish.
- Preserve the document-layer boundaries and navigation model described in
  `docs/README.md` and `docs/index.md` instead of copying the full map into
  every README.
- Keep cross-references purposeful: use them for entry points, owner
  boundaries, required dependencies, or source evidence. Avoid repeated
  historical back-links when a README or index already owns the navigation.
- Add coordination trackers only when there is active cross-document state.
  Keep them compact: current decision points, links, and short coordination
  notes. Move durable detail into narrower owner docs once it has multiple
  active consumers.
- Do not copy an existing validation artifact structure unless the new
  validation question has earned the same artifact types.
