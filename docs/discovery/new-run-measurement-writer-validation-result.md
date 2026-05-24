# New-Run Measurement Writer Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice: **New-Run
Measurement Writer Semantics**.

It does not accept a storage writer, append-only store, checksum contract,
source-file observation, schema inference, live service, callback API, hardware
control, scan execution, GUI workflow, or shared measurement-record schema.

## Fixture

Fixture:
[`../../tests/fixtures/new_run_measurement_writer/basic_1d_run/`](../../tests/fixtures/new_run_measurement_writer/basic_1d_run/)

Implementation candidate:
[`../../implementation_candidates/new_run_measurement_writer/`](../../implementation_candidates/new_run_measurement_writer/)

The fixture records one new Rabi measurement from explicit writer events:

- one `measurement_started` event with expected point count and recording
  enabled state;
- two `data_recorded` events that reference the declared primary data path and
  exact cumulative row counts;
- one `measurement_completed` event with final recorded point count;
- declared 1D table preview metadata for a simple source CSV.

The builder treats the primary data path as a declared reference. It does not
open the CSV, infer columns, count rows from file contents, write storage,
control instruments, stream live updates, render plots, or define a GUI.

## What This Earned

The implementation candidate shows that explicit writer events can produce a
reviewable measurement-record summary before Scopecat owns storage mutation:

- preserve measurement record identity, label, experiment type, target, source
  kind, primary data reference, and declared preview metadata;
- derive lifecycle state from the first and final writer events;
- derive progress counts from explicit writer event totals;
- validate event order: one start event, at least one data event, and a final
  completion or failure event at the end;
- validate nondecreasing event timestamps;
- validate that data-recorded events point at the declared primary data
  reference;
- validate exact cumulative row totals and final recorded point consistency;
- validate bounded primary-data kind, primary-data format, and unique declared
  preview column names for the current fixture shape;
- classify a completed preview-ready record as ready for review;
- classify failed records as reviewable without claiming retry, hardware
  failure, or recovery policy;
- keep storage mutation, source observation, schema inference, live service,
  hardware control, scan execution, and GUI workflow out of scope.

## Boundary

This slice validates writer-event semantics only.

It does not:

- create, copy, append, archive, checksum, or persist measurement data;
- inspect whether referenced primary data files exist or match the declared
  event counts;
- read source files to infer shape, columns, units, row counts, or plot
  candidates;
- define final measurement, lifecycle, progress, storage, or data-shape
  schemas;
- define live event transport, callbacks, websockets, monitor refresh, or GUI
  behavior;
- control hardware, run scans, mutate parameters, retry failed measurements,
  or make safety decisions.

## Result

New-run writer semantics are a useful counterpart to export, incoming-record
import preview, and running inspection. Those slices assume measurement records
exist; this candidate tests the smallest event vocabulary needed to produce one
reviewable measurement-record summary without crossing into storage or runtime
ownership.

The fixture keeps source data and preview metadata explicit. A completed record
must reach the expected point count according to writer events, and each
data-recorded event must advance the cumulative total exactly by its declared
row count. Those are writer-event consistency checks, not file-content
verification or scientific validity.

## Follow-Up

Stop this slice at side-effect-free writer-event validation unless the next
workflow needs actual persistence or live observation.

Likely follow-up slices should stay separate:

- append-only measurement storage writer with explicit filesystem mutation,
  checksum, and no-overwrite or append policy;
- live running writer or monitor transport for already-recorded events,
  without GUI ownership or hardware-control authority;
- harder data-shape writer cases, such as ragged scans, trace-per-point data,
  or array-valued responses, without automatic schema inference.

The first source observation follow-up is now validated separately in
[`measurement-source-observation-validation-result.md`](measurement-source-observation-validation-result.md).
