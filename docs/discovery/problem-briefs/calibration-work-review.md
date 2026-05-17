# Calibration Work Review

## Status

Evidence-backed problem brief.

## User-Facing Failure

Users can express sequential scan and calibration work in notebooks or Python,
but failure, interruption, review gates, continuation, and downstream blocking
remain hard to inspect after the fact. The immediate user need is a clearer
record of what happened and what can happen next, not a general runner.

## Observed Sample Evidence

- Sequential sweep execution, row capture, and interruption behavior are visible
  in static scan/acquisition code.
- Calibration and fitting flows include failed-fit/refit behavior, suspicious
  quality checks, manual-review language, and direct parameter write-back.
- Partial-stop and retry/error evidence exists, but it is not tied to a
  reviewed multi-task queue contract.

## Project-Owner Clarification

- The stronger pain is work-review level: exceptions can break rough queues,
  useful independent work should sometimes continue, and lower-priority
  calibration may run after higher-priority work.
- Record-only intent may leave too much execution burden on users.
- Authoring should stay close to normal Python helper code.

## Derived Hypotheses

- Test whether declared intent plus outcome reports explain review and failure
  better than notebook cells alone.
- A useful validation target may need run-to-completion evidence plus explicit
  blocked/review states before testing resume, retry, review continuation, or
  selected remeasurement.
- Calibration work review is the best candidate episode because it combines
  fit quality, manual decision, continuation, and downstream blocking pressure.

## Out Of Scope For This Brief

- General schedulers, hardware execution, resource leases, and write-back.
- A runner state machine.

## Possible Validation Questions

- Can users understand declared intent versus outcome, review gates, failed
  fit decisions, and downstream blocking without Scopecat owning execution?
- If record-only intent is too weak, what is the smallest local execution proof
  that improves real calibration work without accepting a general runner?
