# Calibration Work Continuation

## Status

Evidence-backed problem brief.

## User-Facing Failure

Users can express sequential scan and calibration work in notebooks or Python,
but failure, interruption, review gates, continuation, and downstream blocking
remain hard to run through and inspect. A record-only plan is unlikely to be
adopted if users still have to manually execute every step, recover every
exception, and decide continuation from scattered notebook state.

## Observed Sample Evidence

- Sequential sweep execution, row capture, and interruption behavior are visible
  in static scan/acquisition code.
- Calibration and fitting flows include failed-fit/refit behavior, suspicious
  quality checks, manual-review language, and direct parameter write-back.
- Partial-stop and retry/error evidence exists, but it is not tied to a
  reviewed, runnable multi-step contract.

## Project-Owner Clarification

- The stronger pain is workflow-continuation level: exceptions can break rough
  queues, useful independent work should sometimes continue, and lower-priority
  calibration may run after higher-priority work.
- Record-only intent leaves too much execution burden on users and is unlikely
  to be adopted as the main calibration improvement.
- Authoring should stay close to normal Python helper code.

## Derived Hypotheses

- The smallest credible validation target should run a bounded local
  calibration workflow while recording intent, progress, blocked/review states,
  outcomes, and requested next action.
- The runtime surface should call ordinary Python/helper steps and record what
  happened; it should not own instrument drivers, timing-critical control, or
  calibration write-back by default.
- Calibration work continuation is a strong candidate episode because it
  combines fit quality, manual decision, continuation, selected remeasurement,
  and downstream blocking pressure.

## Out Of Scope For This Brief

- General schedulers, remote execution, resource leases, hardware-control
  frameworks, and write-back.
- A reusable runner state-machine architecture beyond the smallest validation
  path.

## Possible Validation Questions

- Can a thin local workflow runner execute user-authored calibration steps,
  pause for review, record failed-fit decisions, and continue useful work
  without Scopecat owning hardware control?
- What is the smallest runnable proof that improves real calibration work
  enough to justify runtime scope before accepting a general runner?
