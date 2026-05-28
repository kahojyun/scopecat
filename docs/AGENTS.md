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
- Preserve document-layer boundaries: `docs/evidence/` owns stable evidence
  claims and source posture, `docs/discovery/problem-briefs/` owns current
  problem framing, `docs/discovery/routes/adoption-routes.md` owns route-level
  adoption paths, and `docs/strategy/product-direction.md` owns product
  direction and long-term boundary posture.
- Keep cross-references purposeful: use them for entry points, owner
  boundaries, required dependencies, or source evidence. Avoid repeated
  historical back-links when a README or index already owns the navigation.
- Add coordination trackers only when there is active cross-document state.
  Keep them compact: current decision points, links, and short coordination
  notes. Move durable detail into narrower owner docs once it has multiple
  active consumers.
- Do not copy an existing validation artifact structure unless the new
  validation question has earned the same artifact types.
