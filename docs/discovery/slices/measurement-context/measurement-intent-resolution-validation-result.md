# Measurement Intent Resolution Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Context Backlog subcase:
**Measurement Intent Resolution** under **Measurement Or Step Context Link**.

It does not accept a final measurement-intent schema, final
measurement-record schema, shared context schema, run lifecycle model,
hardware-control contract, parameter write-back contract, setup-mutation
contract, environment manager, code execution contract, restore contract,
workflow DAG, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/measurement_intent_resolution/basic_resolution/`](../../../../tests/fixtures/measurement_intent_resolution/basic_resolution)

Implementation candidate:
[`../../implementation_candidates/measurement_intent_resolution/`](../../../../implementation_candidates/measurement_intent_resolution)

The fixture records one qA chevron intent whose context inputs are moving
selectors:

- current trusted parameter state in a named lineage;
- latest reviewed setup binding for a sample/cooldown;
- reviewed declared environment for the intent, intentionally unavailable.

The run-start resolution receipt freezes available selectors to concrete
context records. The resulting measurement record carries only those resolved
context links. The declared environment selector remains unavailable as an
optional-context review finding.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- keep measurement intent distinct from a measurement record;
- allow measurement intent to carry moving context selectors;
- freeze selected context at run start through an explicit resolution receipt;
- copy only resolved point-in-time context links onto the measurement record;
- keep unresolved optional context as review findings instead of record
  validity failures;
- preserve a prior resolved parameter snapshot even after the lineage current
  pointer moves to a later snapshot;
- reject fixture claims that cross into hardware control, parameter write-back,
  setup mutation, environment sync, code import, or code execution.

## Boundary

This slice validates intent-to-record context resolution only.

It does not:

- define final measurement intent, measurement record, context, lifecycle, or
  storage schemas;
- require context for primary measurement data validity;
- inspect, import, or interpret context payloads;
- read or validate primary measurement data;
- resolve selectors dynamically from a database or filesystem;
- apply parameter state to hardware;
- mutate setup binding;
- sync or validate a runtime environment;
- import, load, or execute selected code;
- restore selected context;
- define a GUI workflow.

## Result

Measurement intent and measurement record are usefully distinct.

Intent can be prospective and selector-shaped: "use the current trusted state
from this lineage" is allowed. The measurement record is retrospective: it
keeps the concrete snapshot that was resolved at run start. If the lineage
later points to a newer snapshot, the record still points to the snapshot that
was actually used.

Context remains optional for the measurement record. Missing optional declared
environment context is visible as a review finding, but it does not make the
record invalid and does not become an automatic run-blocking, readiness,
safety, or reproducibility claim.

## Follow-Up

Stop this slice at explicit run-start resolution unless a concrete workflow
needs stronger behavior.

Likely follow-up slices should stay separate:

- measurement or step context links with zero-context and partial-context
  fixtures, still keeping measurement data valid without context;
- context readiness or status summaries only after repeated workflows need
  sharper review vocabulary;
- selected-reference comparison using resolved record context links, still
  without cause attribution or raw-data comparison;
- dynamic selector resolution against a real context store, only after storage
  authority is separately validated.
