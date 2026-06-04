# Test Agent Instructions

- Keep test stage explicit. A test file should make clear whether it is
  discovery validation, route-local engineering prototype coverage, or
  integration/workflow coverage.
- Discovery tests may import `implementation_candidates`, use
  `candidate_summary`, and assert full expected-output parity.
- Engineering prototype tests should primarily assert route-local behavior:
  request validation, operation state, filesystem effects, receipts, read
  models, review plans, attention paths, and non-mutation guarantees. Candidate
  parity is allowed only as a compatibility check, not the main acceptance
  criterion.
- Integration/workflow tests should start from user-visible entrypoints or
  realistic storage/package state and assert the next usable user step. They
  should not depend on discovery expected-output parity.
- New shared fixture directories must declare their stage posture in the fixture
  README. For small one-off fixtures, declare the stage posture in the owning
  test file instead.
