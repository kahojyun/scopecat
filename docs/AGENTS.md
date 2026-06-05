# Documentation Agent Instructions

- Treat `docs/` as durable project memory. Do not add placeholder structure
  before there is durable content; update existing owner documents before
  creating new structure.
- Keep public-facing documentation under `docs/user/` when introduced, and
  treat it as publishable and redacted by default.
- Keep active task queues, priorities, and implementation checklists in issues,
  PRs, or branch-specific working notes when implementation starts rather than
  stable docs landing pages.
- Keep internal product, architecture, research, decision, and AI-assistive
  material out of user documentation unless it is intentionally promoted.
- Prefer one owning document per durable fact once the fact is accepted or
  current. Cross-link instead of duplicating durable content.
- Preserve the navigation model in `docs/README.md` and `docs/index.md`; avoid
  repeating full maps or historical backlinks in narrower docs.
- Add coordination trackers or validation artifact structures only when active
  cross-document state or a new evidence question has earned them.
