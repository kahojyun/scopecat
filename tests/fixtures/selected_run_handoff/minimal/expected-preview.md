# Expected Selected Run Preview

## Status

Expected output for the selected-run preview spike. This is not a product
plotting UI, data schema contract, or report.

## Source

- selected run: `42`
- experiment: `qA Rabi amplitude sweep`
- target: `qA`
- source file: `source/session-alpha/00042_qA_rabi_20260518_101500.csv`

## Column Validation

- status: `pass`
- declared columns: `bias_v, drive_amp, iq_i, iq_q`
- source columns: `bias_v, drive_amp, iq_i, iq_q`
- missing declared columns: `none`
- extra source columns: `none`
- failures: `none`
- validated: `declared column names against source CSV header; presence of at least one declared sweep axis; presence of at least one declared measured response`
- not validated: `role semantic correctness; unit correctness; held-condition constancy; numeric suitability; scientific validity`

## Preview Table

Rows: `3` of `3`.

| drive_amp | iq_i | iq_q | bias_v |
| --- | --- | --- | --- |
| `0.020` | `0.812` | `0.113` | `0.100` |
| `0.025` | `0.845` | `0.121` | `0.100` |
| `0.030` | `0.831` | `0.116` | `0.100` |

## Plot Spec

- title: `qA Rabi amplitude sweep preview: iq_i`
- x: `drive_amp` (`arb`)
- y: `iq_i` (`arb`)
- held condition: `bias_v = 0.100 V`
- rows used: `3`
- boundary note: Plot-spec-ready display preview only; source export remains separate; no fit, uncertainty, or scientific validation.

## Plot Candidates

| X | Y | Source | Boundary note |
| --- | --- | --- | --- |
| `drive_amp` | `iq_i` | `source/session-alpha/00042_qA_rabi_20260518_101500.csv` | Plot-spec-ready display preview only; source export remains separate; no fit, uncertainty, or scientific validation. |
| `drive_amp` | `iq_q` | `source/session-alpha/00042_qA_rabi_20260518_101500.csv` | Plot-spec-ready display preview only; source export remains separate; no fit, uncertainty, or scientific validation. |

## Caption Stub

qA Rabi amplitude sweep for target qA: iq_i, iq_q versus drive_amp from selected source run 42 (2026-05-18T10:15:00). Calibration notes, fit result, and uncertainty are missing.

## Boundary Notes

- This output is plot-spec preview data, not a rendered plot.
- Column roles come from fixture metadata; the spike does not infer a
  general schema.
- Preview does not provide fit quality, uncertainty, or scientific validity.

## Future Scan Shape Backlog

- `2d_grid_csv`
- `trace_per_point`
- `complex_iq`
- `ragged_steps`
- `npz_companion`
- `derived_table`
