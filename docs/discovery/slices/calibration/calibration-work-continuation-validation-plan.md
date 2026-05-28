# Calibration Work Continuation Validation Plan

## Status

Validation-planning draft.

This is not an ADR, product contract, runner framework, scheduler design, GUI
design, storage schema, parameter schema, hardware-control decision,
instrument-control API, retry policy, write-back policy, remote-execution
design, or resource-arbitration decision. It defines the first narrow
validation question for the calibration work continuation slice.

Owning problem brief:
[`problem-briefs/calibration-work-continuation.md`](../../problem-briefs/calibration-work-continuation.md).

Related evidence:
`EV-005`, `EV-024`, `EV-038`, and `EV-047` in
[`../evidence/evidence-register.md`](../../../evidence/evidence-register.md).

## Validation Question

Can Scopecat represent a small sequence of user-authored calibration steps with
enough explicit continuation, review, failure, output, and requested-next-action
state that a user can resume work better than from scattered notebook state,
and can it identify whether a tiny local execution path is actually needed,
without Scopecat deciding parameter mutation, automatic retry, remote execution,
scheduling, or hardware control?

This slice should pressure work continuation rather than finished-run handoff
or running measurement preview. It should first test whether structured
continuation state can represent calibration intent and review state. Only a
later earned spike should ask whether local execution needs to be bound to that
state.

This slice should stay calibration-specific while it is being validated.
Calibration is the concrete workflow used to discover whether episode, step,
review, output, parameter, write, and continuation concepts are needed. A more
general episode/step/review model is not earned until another slice pressures
the same concepts.

## User Job

During multi-step calibration work, a user wants to start a declared sequence,
let independent or lower-priority steps continue when allowed, pause at review
gates, and later understand what happened well enough to resume manually.

The user needs to know:

- what calibration batch or episode was being attempted;
- which user-authored steps were planned and in what order;
- which target, parameter, or measurement each step relates to;
- which steps completed, failed, were skipped, were blocked, or need review;
- what measurement outputs, fit previews, notes, and parameter snapshots were
  produced;
- what decision is requested from the user before continuation or write-back;
- whether a parameter write was merely proposed, user-declared, or actually
  performed by user-authored code;
- which next actions are available without Scopecat choosing one
  autonomously.

## First Fixture Concept

Start with a synthetic public-safe fixture, not product code:

- one calibration episode with explicit ID, label, target group, and operator
  intent;
- a declared step plan, such as two or three user-authored calibration steps;
- observed continuation context from scattered records, such as measurements,
  fit previews, parameter snapshots, proposed writes, and notes;
- per-step lifecycle state: `pending`, `running`, `completed`, `failed`,
  `skipped`, `blocked`, or `review_needed`, assembled in the expected summary
  rather than supplied as a runner log;
- step-local prerequisites, blocking notes, or continuation conditions declared
  by the user or fixture, such as stop-on-failure for a critical step or
  continue-independent for a later step;
- measurement references or output summaries produced by completed steps;
- fit preview or fit failure state that needs review;
- parameter snapshot references before and after a step when available;
- declared parameter-write records only when the user-authored step or user
  decision explicitly records them;
- requested next action, such as review fit, rerun selected step, skip target,
  accept proposed value outside Scopecat, or continue remaining steps;
- attention-worthy warnings such as missing parameter snapshot, failed fit,
  blocked dependency, ambiguous write authority, missing measurement output, or
  stale continuation context.

The fixture should avoid hardware-control details, raw instrument addresses,
remote paths, executor internals, and private lab identifiers.

The first input should not look like an executor log that already knows the
final summary. It should look like continuation context that Scopecat needs to
assemble: declared intent, declared step plan, observed records, known review
state, known blocking, and missing or uncertain facts.

`declared_step_plan` is interpretive context for the continuation summary, not
a final authoring model or executor input contract. It exists only so observed
records can be related to user intent and planned calibration work.

First fixture:
`tests/fixtures/calibration_work_continuation/review_gate_failed_fit/`.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate summary
should be a pure structured output before any runner implementation:

```text
CalibrationContinuationInput
  -> build_calibration_continuation_summary(...)
  -> CalibrationContinuationSummary
```

The candidate summary may include:

- `episode`: identifier, label, target group, user intent, and local execution
  context label;
- `steps`: ordered user-authored steps with target, purpose, lifecycle state,
  step-local blocking state, fixture-declared continuation condition, and
  source authority;
- `outputs`: measurement references, fit previews, generated artifacts, and
  parameter snapshots produced or expected by steps;
- `review_gates`: decisions requested from the user, including what is known,
  missing, blocked, or unsafe to infer;
- `declared_writes`: user-declared or user-authored parameter-write records,
  separate from Scopecat-decided mutation;
- `requested_next_actions`: available manual continuation choices, not an
  automatic plan;
- `attention`: warnings for failed, missing, blocked, stale, ambiguous, or
  risky states;
- `boundary`: fixture/reviewer notes around local-only execution and
  non-ownership of mutation, retry, scheduling, or hardware control.

Normal state should not be emitted as a warning. For example, `pending`,
`completed`, or `review_needed` can be ordinary lifecycle state. Warnings should
be reserved for attention-worthy conditions: failed fit, blocked dependency,
missing output, ambiguous write authority, stale context, or attempted
continuation without required review.

## Executor Pressure

The problem brief treats record-only continuation state as a usability risk to
validate. That does not mean the first artifact should be an executor or a
general runner.

Use a two-stage path:

1. Create a fixture and expected summary that clarify calibration-continuation
   state without executing code.
2. Only if the summary boundary is coherent, consider a tiny local executor
   spike that runs safe user-authored fixture steps and produces the same
   summary shape.

The executor spike, if earned, should be deliberately small:

- local process only;
- user-authored fixture functions only;
- sequential execution only;
- explicit step order;
- explicit review gates;
- explicit failure and continuation policy;
- no remote execution;
- no concurrency;
- no resource leases;
- no automatic retry;
- no Scopecat-decided parameter mutation;
- no hardware control.

The first executor question is not whether Scopecat can run arbitrary code. The
question is whether binding local execution to calibration intent, progress,
review gates, outputs, and continuation records improves the workflow enough to
justify more design.

## Boundary

Do not include these in the first slice:

- general scheduler;
- remote execution;
- concurrency or resource arbitration;
- hardware-control framework;
- scan-plan mutation;
- automatic retune;
- automatic retry or optimization;
- Scopecat-decided parameter write-back;
- rollback semantics;
- universal parameter schema;
- final fit-quality or user/domain scientific conclusion model;
- GUI implementation;
- durable package/export/import behavior;
- final runner API.

Parameter writes may appear only as explicit user-authored step outputs,
declared write records, or user decisions. They should not become
Scopecat-decided mutations.

## Comparison Pressure Against Earlier Slices

This slice should test whether concepts from earlier validation work generalize:

- `measurement` and source identity remain useful but are not enough; step and
  review state become central;
- preview or fit output may be partial, failed, or review-only;
- warnings should mean attention-worthy workflow state, not ordinary lifecycle
  policy;
- parameter snapshots and declared writes become more important than export
  package membership;
- local execution may be needed, but execution ownership should remain narrow
  and user-authored.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one small calibration-continuation fixture;
- define expected summary output with wrapper and candidate-summary separation;
- include one review gate, one failed or blocked condition, and one possible
  continuation choice;
- keep parameter writes declared and user-authored rather than
  Scopecat-decided;
- defer a tiny local-executor spike until the fixture earns it.

Do not promote a runner, scheduler, parameter, mutation, or hardware-control
architecture decision from this slice alone.
