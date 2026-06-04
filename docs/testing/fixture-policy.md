# Fixture Policy

## Status

Testing policy, not a fixture inventory.

Fixtures should match the test stage they support. Prototype-owned fixtures
live under `tests/fixtures/prototypes/<route>/`. The historical flat
candidate-fixture surface has been removed; the remaining flat fixture family
is bounded scan/data-shape discovery evidence.

## Discovery Fixtures

Discovery fixtures support bounded evidence questions before a live owner
exists.
They may contain:

- `candidate_summary`;
- broad expected-output JSON;
- synthetic boundary cases;
- explicit `does_not_claim` fields;
- internal-validation posture only.

Use discovery fixtures for evidence, not as the main acceptance target for a
promoted prototype. Do not add new fixtures that depend on removed
`implementation_candidates` packages.

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
prior evidence, assert route behavior separately, and migrate the useful case
into `tests/fixtures/prototypes/<route>/` when the test is next changed.

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
Prototype tests should not read from flat fixture directories. Move useful
prototype evidence under the owning route before changing the test.

`expected-receipt.json` and `expected-review.json` normally assert local
receipt or review-summary behavior; they remain repository-safe expected
outputs, not portable/export/package artifacts, unless the route explicitly
promotes that output boundary.

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
