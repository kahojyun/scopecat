# Running Measurement Readability

## Status

Evidence-backed problem brief.

## User-Facing Failure

During long-running measurements, users may need to inspect already-recorded
data, stop or recover from partial runs, and decide whether some analysis unit
is complete, partial, readable, or fit-ready before the full run finishes. The
near-term product pull is closer to a Labber-like monitor for the latest usable
sweep than to in-run scan-plan adjustment.

## Observed Sample Evidence

- Sweep and scan code records rows during iteration.
- Stop/interruption behavior and partial-recording patterns are visible.
- VNA and mesh/landscape scans include start/stop metadata, appended chunks,
  per-sequence companion files, and partial-stop ambiguity.
- Fit/quality review and retune decisions exist, but not as a reason to start
  with complex in-run scan-plan adjustment or automatic next-step advice.
- Recording can be incomplete or disabled through lazy dataset creation,
  `save` flags, `pause_store`, `pause_save`, or bypass paths.

## Project-Owner Clarification

- The near-term need is reading recorded data from a still-running run,
  monitoring the latest useful sweep in a GUI, and knowing readiness at the
  granularity users care about.
- Optional fit or operator-decision evidence may matter after the simpler
  read/monitor value is validated.

## Derived Hypotheses

- Start with explicit recording, progress/readiness markers, and a reader path
  ordinary scripts or a simple GUI monitor can consume.
- Cursor movement, temporary range selection, and preview fits need not be
  durable unless the user saves a fit result or operator decision.

## Out Of Scope For This Brief

- Complex in-run scan-plan adjustment, automatic next-step advice, adaptive
  scan mutation, framework scraping, parameter write-back, and autonomous
  calibration.

## Possible Validation Questions

- Can explicit partial records plus progress/readiness markers let users inspect
  useful parts of a running measurement before it ends?
- Which readiness granularity is real enough to justify changing experiment
  code?
