# Calibration Step Intent Resolution Validation Result

## Status

Implementation candidate validated.

This result validates one narrow calibration workflow slice:
**Calibration Step Intent Resolution**.

It is not a final calibration step schema, context schema, relation graph,
fitting framework, executor, scheduler, write-back contract, hardware-control
contract, storage model, workflow DAG, or GUI design.

Artifact posture: `internal_validation_summary`. This validation result, its
fixture input, and expected output are repository-safe discovery artifacts, not
portable/public export artifacts.

## Fixture

Fixture:
[`../../tests/fixtures/calibration_step_intent_resolution/basic_resolution/`](../../../../tests/fixtures/calibration_step_intent_resolution/basic_resolution)

Implementation candidate:
[`../../implementation_candidates/calibration_step_intent_resolution/`](../../../../implementation_candidates/calibration_step_intent_resolution)

The fixture records one qA Rabi calibration step intent whose context inputs
are moving selectors:

- current trusted parameter state in a named lineage;
- latest reviewed setup binding for a sample/cooldown;
- approved managed calibration code version;
- reviewed declared environment context, intentionally unavailable.

The step-start resolution receipt freezes available selectors to concrete
context records. The resulting calibration step record carries only resolved
context links and a reference-only observation link to a measurement record.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- keep calibration step intent distinct from calibration step record;
- allow calibration step intent to carry moving context selectors;
- freeze selected context at step start through an explicit resolution receipt;
- copy only resolved point-in-time context links onto the step record;
- preserve observation links as references without reading measurement payloads;
- keep unresolved optional context as review findings instead of automatic
  blocking, retry, fitting, continuation, or write-back behavior;
- preserve a prior resolved parameter snapshot even after the lineage current
  pointer moves to a later snapshot;
- reject fixture claims that cross into dynamic selector resolution, fitting,
  calibration execution, continuation decisions, parameter write-back,
  hardware control, scheduling, or measurement payload reads.

## Boundary

This slice validates calibration step intent-to-record context resolution only.

It does not:

- define final calibration step, context, relation graph, lifecycle, storage,
  or package schemas;
- resolve selectors dynamically from storage or a registry;
- read measurement payloads or primary measurement data;
- infer preview metadata;
- run fitting, scoring, or scientific validity checks;
- execute calibration code or measurement code;
- decide continuation, retry, skip, or remeasurement;
- propose, accept, apply, or roll back parameter writes;
- control hardware;
- schedule work;
- recursively traverse adjacent records;
- define a GUI workflow.

## Result

Calibration step intent and calibration step record are usefully distinct.

Intent can be prospective and selector-shaped: "use the current trusted state
from this lineage" is allowed. The step record is retrospective: it keeps the
concrete context snapshots that were resolved at step start. If the lineage
later points to a newer snapshot, the step record still points to the snapshot
that was actually used.

Observation links stay reference-only. The slice can carry an already-declared
observation link reference without reading measurement payloads or running a
fit.

## Follow-Up

Stop this slice at explicit step-start resolution unless a concrete workflow
needs stronger behavior.

Likely follow-up slices should stay separate:

- calibration fit-result reference shape, still without fitting execution or
  score semantics;
- reviewable proposed-write linkage from a step record, still without applying
  writes;
- step-level context-link comparison only after more calibration fixtures need
  comparison;
- dynamic selector resolution against a real context store, only after storage
  authority is separately validated.
