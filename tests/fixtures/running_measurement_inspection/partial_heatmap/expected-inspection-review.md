# Expected Running Measurement Inspection Review

## Fixture Wrapper

- expected output id: `running-inspection-partial-heatmap.expected`
- status: `expected_validation_output`
- source fixture: `inspection-input.json`
- reference semantics: `fixture_paths_are_package_relative`

This is not a final lifecycle schema, live service contract, GUI design, reader
API, plotting API, or hardware-control decision. Fixture path values are
package-relative files used for public-safe validation.

## Candidate Summary Review

### Measurement

- measurement: `run-live-03001`
- legacy data id: `3001`
- label: `qA live flux spectroscopy map`
- target: `qA`
- source identity: `LAB_LOCAL:/redacted/datavault/live-heatmap-demo/flux-spectroscopy-live-source.csv`

### Lifecycle And Progress

- lifecycle state: `recording`
- recording enabled: `true`
- recorded points: `13` of `20`
- recorded rows: `2` of `4`
- latest completed unit: rectangular prefix, `2` rows, `10` points, complete, default preview candidate
- current partial unit: grid row at `bias_v = 0.02`, `3` of `5` points, incomplete, not a default preview candidate

The fixture distinguishes objective completeness from GUI visibility.
Incomplete running data can still be shown, but the rectangular prefix is the
stable default preview candidate. The incomplete row is normal
running-measurement state, not a warning by itself.

### Preview

- status: `preview_ready`
- shape: `partial_2d_grid_table`
- axes: `bias_v`, `drive_freq_ghz`
- row order: `bias_v_outer_drive_freq_ghz_inner_fastest`
- grid assumption: `rectangular_prefix_plus_current_partial_row`
- heatmap candidates: `drive_freq_ghz` x `bias_v` -> `signal_db`; `drive_freq_ghz` x `bias_v` -> `phase_deg`

### Latest Data Reference

- path: `source/live-heatmap-demo/flux-spectroscopy-live-partial-source.csv`
- kind: `partial_recorded_table`
- latest completed filter: `bias_v <= 0`

### Monitor State

- selected region: `drive_freq_ghz` from `4.99` to `5.01`; `bias_v` from `-0.02` to `0`
- temporary feature preview: `minimum_signal_marker`, `preview_only`, computed over the latest completed unit
- durable monitor state: `false`

Temporary region selection and feature markers are monitor ergonomics. They are
not durable records unless the user saves a fit result, marker, or operator
decision.

### Attention

- none

Latest data age is `8` seconds against a fixture-declared stale threshold of
`60` seconds.

## Boundary Notes

- Scopecat is not controlling instruments or changing scan plans in this slice.
- Recording, partial progress, and non-final state are normal summary states,
  not warnings.
- This fixture checks that the same running-inspection state categories can
  describe a 2D heatmap preview without defining ragged scan, array-valued
  storage, or final plotting contracts.
- The fixture does not define a final source of truth for runtime, disk,
  adapter, or storage authority.
- The fixture does not validate fit quality, scientific validity, or
  reproducibility.

## Reviewer Questions

A reviewer should be able to answer:

- which measurement is currently running;
- how much 2D grid data has been recorded;
- which rectangular prefix is structurally complete and preferred as the
  default preview;
- whether preview metadata can orient a heatmap monitor;
- whether any attention-worthy state exists;
- whether monitor-only region and marker state has been saved durably;
- that Scopecat is not claiming hardware control or scan-plan mutation.
