# Test Agent Instructions

- Let the directory layout carry stage intent: `tests/prototypes/<owner>/` for
  implementation-owner behavior, `tests/integration/<workflow>/` for
  user-visible workflows, and flat root tests only for bounded repository-level
  checks such as scan/data-shape discovery evidence.
- Do not import removed discovery candidates, recreate old candidate fixture
  shapes, or make candidate-summary parity the acceptance boundary.
- Keep fixtures small, explicit, repository-safe, and named by the behavior
  they support. Add a fixture README only when the fixture purpose is not clear
  from its path and owning test.
