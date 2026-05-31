# Context Inclusion Semantics Validation Result

## Status

Implementation candidate validated.

This is not an ADR, reusable template language, universal context schema,
migration requirement, run-blocking contract, GUI design, hardware-control
contract, parameter write-back contract, environment manager, or executor.

## Inputs

- [`prepared-run-context-validation-result.md`](prepared-run-context-validation-result.md)
- [`run-preparation-workflow-boundary-validation-result.md`](run-preparation-workflow-boundary-validation-result.md)
- [`context-inclusion-semantics-validation-plan.md`](context-inclusion-semantics-validation-plan.md)
- `tests/fixtures/context_inclusion_semantics/basic_semantics/`
- `implementation_candidates/context_inclusion_semantics/`

## Validated Boundary

The fixture and implementation candidate validate a narrow context-inclusion
semantics boundary:

- selected context references with IDs are recorded;
- selected optional context is recorded even when `required=false`;
- `required` controls absence severity only;
- unavailable required context becomes a review finding;
- unavailable optional context and optional-not-selected context become
  informational notes;
- `requirement_source` can distinguish opportunistic recording from declared
  template or manual-preparation policy pressure;
- opportunistic recording cannot mark a context as required;
- no reusable template language, global required context families, migration
  requirement from old experiment code, run-blocking contract, hardware
  control, parameter write-back, environment sync, code execution, GUI
  behavior, or shared context schema is accepted.

## What The Summary Can Answer

The candidate summary can answer:

- which selected contexts are recorded;
- which selected contexts were optional but still recorded;
- which unavailable contexts are required review findings;
- which absent optional contexts are informational only;
- which local policy source made absence significant;
- why context inclusion does not force migration to complete Scopecat-managed
  context before recording useful run context.

## Remaining Questions

- Should a later reusable template slice define concrete required inputs?
- Should manual review gates consume `requirement_source` directly, or keep
  using normalized required-absence findings?
- Should GUI copy distinguish "recorded optional context" from "required
  template input"?

## Not Earned

This validation does not earn:

- reusable template language;
- global required context families;
- migration requirement from legacy experiment code;
- run-blocking contract;
- hardware control;
- parameter write-back;
- environment sync;
- code import or execution;
- GUI workflow;
- shared context schema.

## Validation

- `uv run python -m unittest tests.test_context_inclusion_semantics_fixture tests.test_context_inclusion_semantics_summary_candidate`

## Slice Recommendation

Stop this slice at context inclusion semantics. Likely follow-ups are revising
older fixtures as they are touched, or validating a minimal reusable template
input contract separately.
