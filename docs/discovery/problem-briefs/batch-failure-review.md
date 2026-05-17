# Batch Failure And Review

## Status

Evidence-backed problem brief.

## User-Facing Failure

Users can express sequential scan and calibration work in notebooks or Python,
but failure, interruption, review gates, continuation, and downstream blocking
remain hard to inspect after the fact. A complex intent record alone is not
enough if users still have to parse and execute it manually.

## Observed Sample Evidence

- Sequential sweep execution, row capture, and interruption behavior are visible
  in static scan/acquisition code.
- Calibration and fitting flows include failed-fit/refit behavior, suspicious
  quality checks, manual-review language, and direct parameter write-back.
- Partial-stop and retry/error evidence exists, but it is not tied to a
  reviewed multi-task queue contract.

## Project-Owner Clarification

- The stronger pain is queue-level: exceptions can break rough queues, useful
  independent work should sometimes continue, and lower-priority calibration may
  run after higher-priority work.
- A minimal local executor or standalone package may be needed for adoption
  because record-only intent leaves too much execution burden on users.
- The authoring surface should feel like helper/builder code or decorated
  functions, not hand-written manifest files.

## Derived Hypotheses

- Start by testing declared intent plus observed or simulated outcome reports.
- A useful validation target may need run-to-completion evidence plus explicit
  blocked/review states before testing resume, retry, review continuation, or
  selected remeasurement.
- Calibration batch review is the best candidate episode because it combines
  fit quality, manual decision, continuation, and downstream blocking pressure.

## Current Boundary

- Task DAG semantics, blocked-task accounting, priority arbitration, idle
  backfill, resource leases, and managed continuation after failure.
- Scopecat-owned scheduling, retries, locking, hardware execution, or
  write-back.
- Treating status vocabulary as a runner state machine.

## Possible Validation Questions

- Can users understand declared intent versus outcome, review gates, failed
  fit decisions, and downstream blocking without Scopecat owning execution?
- If record-only intent is too weak, what is the smallest local execution proof
  that improves real calibration work without accepting a general runner?
