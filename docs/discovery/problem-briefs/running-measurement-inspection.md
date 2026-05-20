# Running Measurement Inspection

## Status

Evidence-backed problem brief.

## User-Facing Failure

During long-running measurements, users may need to inspect already-recorded
data, stop or recover from partial runs, and decide whether a recorded portion
is structurally complete, still partial, or useful enough for inspection or a
temporary fit preview before the full run finishes.
The near-term product pull is closer to a Labber-like monitor for the latest
usable sweep than to in-run scan-plan adjustment.

## Observed Sample Evidence

- Sweep and scan code records rows during iteration.
- Stop/interruption behavior and partial-recording patterns are visible.
- VNA and mesh/landscape scans include start/stop metadata, appended chunks,
  per-sequence companion files, and partial-stop ambiguity.
- Existing LabRAD Grapher use includes selecting a range in live data and
  fitting a parabola, which is a useful reference for monitor ergonomics.
- Fit/quality review and retune decisions exist, but not as a reason to start
  with complex in-run scan-plan changes or automatic retune.
- Recording can be incomplete or disabled through lazy dataset creation,
  `save` flags, `pause_store`, `pause_save`, or bypass paths.

## Project-Owner Clarification

- The near-term need is reading recorded data from a still-running run,
  monitoring the latest useful sweep through a simple monitor surface, and
  knowing completeness at the granularity users care about.
- Range selection and parabolic-fit affordances are part of the existing user
  expectation, but they do not need durable records unless the user saves a fit
  result or operator decision.

## Derived Hypotheses

- Start with explicit recording, progress/completeness markers, and a reader
  path ordinary scripts or a simple monitor can consume.
- Cursor movement and temporary range selection need not be durable unless the
  user saves a fit result or operator decision.
- User-requested preview computation, such as fitting a parabola over a
  selected range, can be part of monitor usefulness without becoming automatic
  retune or scan-plan control.

## Out Of Scope For This Brief

- Complex in-run scan-plan changes, automatic retune/write-back, framework
  scraping, and autonomous calibration.

## Possible Validation Questions

- Can explicit partial records plus progress/readiness markers let users inspect
  useful parts of a running measurement before it ends?
- Does range selection plus parabolic fitting make the monitor useful enough
  without promoting automatic retune or scan-plan control?
- Which readiness granularity is concrete enough to justify changing experiment
  code?
