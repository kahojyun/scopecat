# Expected Running Measurement Inspection Review

## Fixture Wrapper

- expected output id: `running-inspection-partial-sweep.expected`
- status: `expected_validation_output`
- source fixture: `inspection-input.json`
- reference semantics: `fixture_paths_are_package_relative`

This is not a final lifecycle schema, live service contract, GUI design, reader
API, plotting API, or hardware-control decision. Fixture path values are
package-relative files used for public-safe validation.

## Candidate Summary Review

### Measurement

- measurement: `run-live-02001`
- legacy data id: `2001`
- label: `qA resonator live frequency sweep`
- target: `qA`
- source identity: `LAB_LOCAL:/redacted/datavault/session-beta/02001_qA_resonator_live.csv`

### Lifecycle And Progress

- lifecycle state: `recording`
- recording enabled: `true`
- recorded points: `14` of `30`
- recorded sweeps: `1` of `3`
- latest completed unit: sweep `0`, `10` rows, complete, default preview candidate
- current partial unit: sweep `1`, `4` of `10` points, incomplete, not a default preview candidate

The fixture distinguishes objective completeness from GUI visibility.
Incomplete running data can still be shown, but the complete sweep is the stable
default preview candidate. Partial progress is summary state, not a warning by
itself.

### Preview

- status: `preview_ready`
- shape: `repeated_1d_sweep_table`
- axis: `drive_freq_ghz`
- repeat axis: `sweep_index`
- row order: `sweep_index_blocks_drive_freq_ghz_inner_fastest`
- plot candidates: `drive_freq_ghz` -> `response_i`; `drive_freq_ghz` -> `response_q`

### Latest Data Reference

- path: `source/session-beta/02001_qA_resonator_live_partial.csv`
- kind: `partial_recorded_table`
- latest completed filter: `sweep_index == 0`

### Monitor State

- selected range: `drive_freq_ghz` from `4.996` to `5.006`
- temporary fit preview: `parabolic_fit`, `preview_only`, vertex `5.001`
- durable monitor state: `false`

Temporary range selection and preview fits are monitor ergonomics. They are not
durable records unless the user saves a fit result or operator decision.

### Attention

- `latest_data_stale`: Latest update is 92 seconds before the fixture
  observation time; stale threshold is `60` seconds.

## Boundary Notes

- Scopecat is not controlling instruments or changing scan plans in this slice.
- Recording, partial progress, and non-final state are normal summary states,
  not warnings.
- The fixture does not define a final source of truth for runtime, disk,
  adapter, or storage authority.
- The fixture does not validate fit quality, scientific validity, or
  reproducibility.

## Reviewer Questions

A reviewer should be able to answer:

- which measurement is currently running;
- how much data has been recorded;
- which unit is structurally complete and preferred as the default preview;
- whether preview metadata can orient a monitor;
- whether any attention-worthy state exists;
- whether monitor-only fit/range state has been saved durably;
- that Scopecat is not claiming hardware control or scan-plan mutation.
