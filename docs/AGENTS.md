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
- Prefer one owning document per durable fact. Cross-link instead of
  duplicating, and make accepted decisions, validation scope, contracts,
  hypotheses, and open questions easy to distinguish.
- Preserve document-layer boundaries: `docs/evidence/` owns stable evidence
  claims and source posture, `docs/discovery/problem-briefs/` owns current
  problem framing, `docs/product/adoption-strategy.md` owns current product
  adoption paths, `docs/product/target-journeys.md` owns target product
  journeys, `docs/product/target-capabilities.md` owns product capability
  maturity, `docs/brownfield/` owns current-state assessment, transition
  architecture, migration strategy, and migration roadmap,
  `docs/decisions/register.md` owns cross-document decision indexing,
  `docs/engineering/implementation-register.md` owns live implementation
  ownership, and `docs/product/direction.md` owns product direction and
  long-term boundary strategy.
- Keep cross-references purposeful: use them for entry points, owner
  boundaries, required dependencies, or source evidence. Avoid repeated
  historical back-links when a README or index already owns the navigation.
- Keep top-down orientation in `docs/README.md` and flat inventory in
  `docs/index.md`; do not make every README repeat the full document map.
- Add coordination trackers only when there is active cross-document state.
  Keep them compact: current decision points, links, and short coordination
  notes. Move durable detail into narrower owner docs once it has multiple
  active consumers.
- Do not copy an existing validation artifact structure unless the new
  validation question has earned the same artifact types.
