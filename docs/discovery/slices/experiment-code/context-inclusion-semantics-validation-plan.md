# Context Inclusion Semantics Validation Plan

## Status

Validation plan for an implementation candidate.

This is not an ADR, reusable template language, universal context schema,
migration requirement, run-blocking contract, GUI design, hardware-control
contract, parameter write-back contract, environment manager, or executor.

## User Job

Let users record available prepared-run context references opportunistically
while using `required` only to express absence severity from a local preparation
or template policy. A selected context with an ID should be recorded even when
`required=false`; old experiment code should not need to migrate every possible
context before Scopecat can record useful context.

## Boundary To Validate

- `include_state=selected` with a `context_id` records the referenced context;
- selected optional context is still recorded;
- `required` controls how missing or unavailable context is surfaced;
- required unavailable context becomes a review finding;
- optional unavailable or optional-not-selected context remains informational;
- `requirement_source` records why absence matters, but does not define a
  template language;
- opportunistic context recording cannot make a context required;
- no migration requirement, global required family list, run blocking,
  hardware control, parameter write-back, environment sync, code execution, GUI
  behavior, or shared context schema is accepted.

## Fixture

Use `tests/fixtures/context_inclusion_semantics/basic_semantics/`.

The fixture is repository-safe synthetic data. It includes one required
template parameter-state input, two selected optional/opportunistic contexts,
one unavailable optional environment context, one optional-not-selected station
context, and one unavailable required manual-preparation context. The
validation summary posture is `internal_validation_summary`.

## Validation Steps

1. Validate fixture JSON and expected summary shape.
2. Validate context-inclusion policy and side-effect non-claims.
3. Validate selected references resolve to family-owned context records.
4. Validate selected optional references are recorded.
5. Validate optional absent contexts produce informational notes only.
6. Validate unavailable required contexts produce review findings.
7. Reject opportunistic references marked required.

## Tests

- `tests/test_context_inclusion_semantics_fixture.py`
- `tests/test_context_inclusion_semantics_summary_candidate.py`

Run:

```bash
uv run python -m unittest tests.test_context_inclusion_semantics_fixture tests.test_context_inclusion_semantics_summary_candidate
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```
