# Test Agent Instructions

- Keep test stage explicit. A test file should make clear whether it is
  discovery validation, route-local engineering prototype coverage, or
  integration/workflow coverage.
- Historical discovery candidates have been removed from the active test
  surface. New tests must not import `implementation_candidates` or make
  `candidate_summary` parity the acceptance boundary.
- Engineering prototype tests should primarily assert route-local behavior:
  request validation, operation state, filesystem effects, receipts, read
  models, review plans, attention paths, and non-mutation guarantees. Candidate
  parity is allowed only as clearly labeled prior-evidence compatibility while
  the fixture is being migrated, not the main acceptance criterion.
- Integration/workflow tests should start from user-visible entrypoints or
  realistic storage/package state and assert the next usable user step. They
  should not depend on discovery expected-output parity.
- New shared fixture directories must declare their stage posture in the fixture
  README. For small one-off fixtures, declare the stage posture in the owning
  test file instead.
