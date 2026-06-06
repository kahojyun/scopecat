# Fixture Policy

## Status

Testing policy.

Fixtures should match the test stage they support. Prototype-owned fixtures
live under `tests/fixtures/prototypes/<owner>/`. Integration fixtures, when
needed, live under `tests/fixtures/integration/<workflow>/`. Discovery evidence
fixtures live under `tests/fixtures/discovery/<topic>/`.

## Discovery Fixtures

Discovery fixtures support bounded evidence questions before a live owner
exists.
They may contain:

- broad expected-output JSON;
- synthetic boundary cases;
- internal-validation posture only.

Use discovery fixtures for evidence, not as the main acceptance target for a
promoted prototype. Do not add fixtures that depend on candidate packages or
recreate old candidate summary shapes.

Discovery fixture notes are evidence-local. They do not own active route
boundaries, architecture decisions, or accepted non-claims.

New discovery fixture families need a named evidence question and should use
plain input and expected-output names that describe that question directly.

## Prototype Fixtures

Prototype fixtures support implementation-owner behavior. They should prefer
inputs that look like requests, commands, local packages, storage roots,
operation receipts, or review-plan inputs for that owner.

Do not put fixture classification metadata inside prototype payloads. The
fixture path, test name, and an optional directory README should carry case
identity and fixture intent.

Boundary, policy, posture, and authority fields may appear in fixtures only
when they are real request, package, receipt, or summary fields consumed or
emitted by the code under test. They should not be used as fixture-local
guardrail comments.

Prefer module-owned constants or typed request/result builders for invariant
owner policy. Accepted boundary and decision documents own boundary guidance,
while tests assert the behavior that matters.

Prototype fixtures should avoid making prior discovery summaries the central
object. If prior evidence is still useful, keep it clearly named as prior
evidence, assert owner behavior separately, and migrate the useful case into
`tests/fixtures/prototypes/<owner>/` when the test is next changed.

Recommended layout for new prototype fixtures:

```text
tests/fixtures/prototypes/<owner>/<workflow-step>/
  request.json
  storage/
  package/
  content/
  expected-receipt.json
  expected-review.json
  README.md
```

Not every directory needs every subdirectory. Keep fixtures small and explicit.
Prototype tests should not read from unrelated flat fixture directories. Move
useful prototype evidence under the owning implementation owner before
changing the test.

`expected-receipt.json` and `expected-review.json` normally assert local
receipt or review-summary behavior; they remain repository-safe expected
outputs, not portable/export/package artifacts, unless the route explicitly
promotes that output boundary.

## Integration Fixtures

Integration fixtures support cross-owner or user-visible workflows. They
should model realistic local state and avoid discovery expected-output parity
as the acceptance target.

Integration tests may reuse prototype fixtures as input state when the
workflow intentionally starts from an accepted owner behavior. Add a
dedicated `tests/fixtures/integration/<workflow>/` fixture only when the
workflow needs its own cross-route state, expected outputs, or non-obvious
setup.

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
