# Documentation Agent Instructions

- Treat `docs/` as long-lived project memory, not as a session scratchpad.
- Do not create placeholder directories, sentinel files, or broad scaffolds
  before there is durable content for them.
- Keep public-facing documentation under `docs/user/` when it is introduced.
- Treat `docs/user/` as publishable and redacted by default.
- Keep internal product, architecture, research, decision, and AI-assistive
  material out of user documentation unless it is intentionally promoted.
- Use journey-first product discovery: user journeys and pain points should be
  shared project artifacts, not duplicated per subsystem.
- Use capability-first adoption stories: each capability may have an
  independent adoption path, derived from shared journeys.
- Treat subsystem or capability docs as ownership and contract documents, not
  as isolated product-research universes.
- Prefer one owning document per durable fact. Cross-link instead of
  duplicating.
- Mark hypotheses, accepted decisions, and open questions explicitly when the
  distinction matters.
- Keep trackers compact. Trackers may own status, current decision points, and
  links; move durable ladder, wedge, baseline, or contract detail into the
  narrowest owner document once it has multiple active consumers.
- Treat mature journey folders as earned exemplars, not templates to copy
  wholesale. Future journey folders should start with the smallest useful
  selection, journey, and fixture/source-map notes, then add later artifacts
  only when promoted.
- Prefer decision-first read paths for implementation and review work. Process
  history is useful, but accepted decisions, validation scope, and contracts
  should be easy to find directly.
