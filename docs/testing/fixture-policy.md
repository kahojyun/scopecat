# Fixture Policy

## Status

Testing policy, not a fixture inventory.

Fixtures should match the test stage they support. Prototype-owned fixtures
live under `tests/fixtures/prototypes/<route>/`; many historical discovery and
candidate fixture directories intentionally remain in the flat layout for now.

## Discovery Fixtures

Discovery fixtures support implementation candidates and validation slices.
They may contain:

- `candidate_summary`;
- broad expected-output JSON;
- synthetic boundary cases;
- explicit `does_not_claim` fields;
- internal-validation posture only.

Use discovery fixtures for evidence, not as the main acceptance target for a
promoted prototype.

Recommended layout for new discovery fixtures:

```text
tests/fixtures/discovery/<slice>/<case>/
  <slice>-input.json
  expected-<slice>-summary.json
  README.md
```

## Prototype Fixtures

Prototype fixtures support route-local engineering behavior. They should
prefer inputs that look like route requests, commands, local packages, storage
roots, operation receipts, or review-plan inputs.

Prototype fixtures should avoid making `candidate_summary` the central object.
If a discovery summary is required as prior evidence, keep it clearly named as
prior evidence and assert route behavior separately.

Recommended layout for new prototype fixtures:

```text
tests/fixtures/prototypes/<route>/<workflow-step>/
  request.json
  storage/
  package/
  content/
  expected-receipt.json
  expected-review.json
  README.md
```

Not every directory needs every subdirectory. Keep fixtures small and explicit.
If a prototype test still uses prior discovery evidence, leave that shared
fixture in the discovery/candidate location until the candidate tests are
retired or migrated together.

## Integration Fixtures

Integration fixtures support cross-route or user-visible workflows. They should
model realistic local state and avoid discovery expected-output parity as the
acceptance target.

Recommended layout for new integration fixtures:

```text
tests/fixtures/integration/<workflow>/
  input/
  storage/
  package/
  expected/
  README.md
```

## Repository Safety

All fixture stages must remain repository-safe:

- no real secrets, tokens, hostnames, private paths, customer/user/lab IDs, or
  accidental local filesystem leaks;
- required input fields should appear in the fixture or test case, not be
  silently supplied by helpers;
- runtime redaction is required only at declared portable/public/export
  boundaries.
