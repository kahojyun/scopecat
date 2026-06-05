# Test Agent Instructions

- Let the directory layout carry stage intent: `tests/prototypes/<route>/` for
  route-local behavior, `tests/integration/<route>/` for user-visible
  cross-route workflows, and flat root tests only for bounded repository-level
  discovery checks.
- Do not import removed discovery candidates or make candidate-summary parity
  the acceptance boundary.
- Keep fixtures small, explicit, repository-safe, and named by the behavior
  they support. Add a fixture README only when the fixture purpose is not clear
  from its path and owning test.
