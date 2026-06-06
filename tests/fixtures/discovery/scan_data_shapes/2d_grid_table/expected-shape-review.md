# Expected 2D Grid Table Shape Review

## Status

Expected reviewer-facing output for the synthetic `2d_grid_table` fixture. This
is not a storage schema, plotting API, file importer, or product contract.

## Measurement

- measurement: `synthetic-meas-02001`
- label: `qA frequency response map`
- target: `qA`
- source kind: `primary_measurement`
- source table: `source/declared-2d-frequency-response-grid.csv`

## Declared Shape

- kind: `2d_grid_table`
- grid assumption: `rectangular_complete_grid`
- axis order: `bias_v`, `drive_frequency_ghz`
- expected point count: `6`
- actual row count: `6`
- status: `pass`

## Axes And Dependents

| Name | Label | Role | Unit |
| --- | --- | --- | --- |
| `bias_v` | Bias | sweep axis | `V` |
| `drive_frequency_ghz` | Drive frequency | sweep axis | `GHz` |
| `signal_db` | Signal magnitude | measured response | `dB` |
| `phase_deg` | Signal phase | measured response | `deg` |

Held condition:

- Readout power: `-20 dBm` (`fixture_declared`)

## Column Validation

- status: `pass`
- declared columns: `bias_v`, `drive_frequency_ghz`, `signal_db`, `phase_deg`
- source columns: `bias_v`, `drive_frequency_ghz`, `signal_db`, `phase_deg`, `operator_note`
- missing declared columns: `none`
- extra source columns: `operator_note`

## Plot Candidates

| X | Y | Z | Source | Boundary note |
| --- | --- | --- | --- | --- |
| `drive_frequency_ghz` | `bias_v` | `signal_db` | `source/declared-2d-frequency-response-grid.csv` | Plot candidates are declared 2D grid plot candidates only; no rendering, fit, uncertainty, or scientific validation is provided. |
| `drive_frequency_ghz` | `bias_v` | `phase_deg` | `source/declared-2d-frequency-response-grid.csv` | Plot candidates are declared 2D grid plot candidates only; no rendering, fit, uncertainty, or scientific validation is provided. |

## Warnings

- `extra_source_column`: source table contains undeclared `operator_note`. It
  is reported but not treated as plot metadata.

## Boundary Notes

- The 2D grid shape comes from fixture declaration, not schema inference.
- Plot candidates are declared 2D grid plot candidates only; no rendering,
  fit, uncertainty, or scientific validation is provided.
- This fixture validates declared shape consistency only, not scientific
  correctness.

## Reviewer Questions

A reviewer should be able to answer:

- which two axes define the grid;
- which measured responses can become plot candidates;
- whether the grid is declared rectangular and complete;
- which source columns are declared versus extra;
- what is mechanically checked and what remains unvalidated;
- that this fixture tests model adequacy, not a final storage or plotting API.
