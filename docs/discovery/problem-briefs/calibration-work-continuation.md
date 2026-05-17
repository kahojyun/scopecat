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
- In the minimal version, this executor has a similar risk profile to a user
  running the same steps through an IPython or notebook cell queue. It becomes a
  different risk class when it adds unattended autonomy, retries with mutation,
  concurrency, remote execution, resource arbitration, hardware safety policy,
  or calibration write-back.
- Calibration work continuation is a strong candidate episode because it
  combines fit quality, manual decision, continuation, selected remeasurement,
  and downstream blocking pressure.

## Out Of Scope For This Brief

- General schedulers, remote execution, resource leases, hardware-control
  frameworks, unattended autonomy, automatic mutation/retry policy, and
  write-back.
- A reusable runner framework beyond the smallest local sequential executor.

## Possible Validation Questions

- Can a local sequential executor run user-authored calibration steps, pause for
  review, record failed-fit decisions, and continue useful work better than a
  notebook cell queue?
- What is the smallest runnable proof that improves real calibration work
  before accepting general scheduling, remote execution, automatic retry, or
  write-back scope?
