# Calibration Work Continuation

## Status

Evidence-backed problem brief.

This brief preserves evidence only. Current journey/use-case ownership lives
in [`../../product/target-journeys.md`](../../product/target-journeys.md);
validation evidence lives in
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md).

## User-Facing Failure

Users can express sequential scan and calibration work in notebooks or Python,
but failure, interruption, review gates, continuation, and downstream blocking
remain hard to run through and inspect. A record-only plan may not meet the
usability bar if users still have to manually queue every step, recover every
exception, and decide continuation from scattered notebook state.

## Observed Sample Evidence

- Sequential sweep execution, row capture, and interruption behavior are visible
  in static scan/acquisition code.
- Calibration and fitting flows include failed-fit/refit behavior, suspicious
  quality checks, manual-review language, and direct parameter write-back.
- Partial-stop and retry/error evidence exists, but IPython or notebook cell
  queues do not provide a clear contract for reviewed, runnable multi-step
  calibration work.

## Project-Owner Clarification

- The stronger pain is the gap between simple cell queuing and real multi-step
  calibration work: exceptions can break rough queues, useful independent work
  should sometimes continue, and lower-priority calibration may run after
  higher-priority work.
- Record-only intent may leave too much execution burden on users. The first
  credible validation should test whether structured continuation records are
  enough, or whether a small local sequential executor is needed.
- Authoring should stay close to normal Python helper code.

## Derived Hypotheses

- The first validation target should clarify the continuation record: declared
  user-authored steps, intent, progress, blocked/review states, outcomes, and
  requested next action.
- If record-only continuation state is not enough, the next likely test is a
  small local sequential execution path inside the same local arbitrary-code
  context as IPython or a notebook.
- The important boundary is not "can it execute code"; it is whether Scopecat
  crosses into remote execution, open-ended autonomy, concurrency, resource
  arbitration, Scopecat-decided mutation/retry policy, or Scopecat-decided
  calibration write-back.
- If an execution path is validated, the differentiator should be calibration
  intent, review gates, failure policy, outputs, parameter/run/code context,
  and follow-on analysis or diagnostics, not a new general-purpose executor.
- The actual invocation mechanism could be a thin wrapper around an existing
  Python process, workflow, or task-running library.
- Calibration work continuation is a strong candidate episode because it
  combines fit quality, manual decision, continuation, selected remeasurement,
  and downstream blocking pressure.

## Out Of Scope For This Brief

- General schedulers, remote execution, resource leases, hardware-control
  frameworks, open-ended autonomy, Scopecat-decided mutation/retry policy, and
  Scopecat-decided write-back.
- A reusable runner framework.

## Possible Validation Questions

- Can structured continuation records capture user-authored calibration steps,
  review gates, failed-fit decisions, and useful continuation choices well
  enough to improve on scattered notebook state?
- If record-only state is insufficient, can a small local sequential execution
  path run user-authored calibration steps, pause for review, record outcomes,
  and continue useful work better than a notebook cell queue?
- What is the smallest runnable proof that improves real calibration work
  before accepting remote execution, open-ended autonomy, resource arbitration,
  Scopecat-decided retry/mutation, or Scopecat-decided write-back scope?
