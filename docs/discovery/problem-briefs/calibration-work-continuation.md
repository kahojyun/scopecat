# Calibration Work Continuation

## Status

Evidence-backed problem brief.

## User-Facing Failure

Users can express sequential scan and calibration work in notebooks or Python,
but failure, interruption, review gates, continuation, and downstream blocking
remain hard to run through and inspect. A record-only plan will not create
enough user value if users still have to manually execute every step, recover
every exception, and decide continuation from scattered notebook state.

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
- Record-only intent leaves too much execution burden on users. The first
  credible product shape needs a small local executor.
- Authoring should stay close to normal Python helper code.

## Derived Hypotheses

- The smallest credible validation target is a local sequential batch executor:
  it runs user-authored Python/helper steps one after another while recording
  intent, progress, blocked/review states, outcomes, and requested next action.
- In the minimal version, this executor stays inside the same local arbitrary
  code execution context as IPython or a notebook. The important boundary is not
  "can it execute code"; it is whether Scopecat crosses into remote execution,
  open-ended autonomy, concurrency, resource arbitration, automatic
  mutation/retry policy, or calibration write-back.
- The differentiator is not a new general-purpose executor. Scopecat should
  bind execution to calibration intent, review gates, failure policy, outputs,
  parameter/run/code context, and follow-on analysis or diagnostics.
- The actual invocation mechanism may be a thin wrapper around an existing
  Python process, workflow, or task-running library.
- Calibration work continuation is a strong candidate episode because it
  combines fit quality, manual decision, continuation, selected remeasurement,
  and downstream blocking pressure.

## Out Of Scope For This Brief

- General schedulers, remote execution, resource leases, hardware-control
  frameworks, open-ended autonomy, automatic mutation/retry policy, and
  write-back.
- A reusable runner framework beyond the smallest local sequential executor.

## Possible Validation Questions

- Can a local sequential executor run user-authored calibration steps, pause for
  review, record failed-fit decisions, and continue useful work better than a
  notebook cell queue?
- What is the smallest runnable proof that improves real calibration work
  before accepting remote execution, open-ended autonomy, resource arbitration,
  automatic retry/mutation, or write-back scope?
