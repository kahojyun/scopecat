# Expected Ragged Adaptive Table Shape Review

## Status

Expected reviewer-facing output for the synthetic `ragged_adaptive_table`
fixture. This is not a storage schema, plotting API, file importer, or
product contract.

## Measurement

- measurement: `synthetic-meas-02003`
- label: `qA adaptive frequency response`
- target: `qA`
- source kind: `primary_measurement`
- source table: `source/ragged-adaptive-frequency-response.csv`

## Declared Shape

- kind: `ragged_adaptive_table`
- ragged assumption: `declared_variable_inner_axis`
- axis order: `bias_v`, `drive_frequency_ghz`
- grouping axis: `bias_v`
- ragged axis: `drive_frequency_ghz`
- total row count: `9`
- status: `pass`

Group coverage:

| Group | Expected points | Observed points |
| --- | --- | --- |
| `0.0` | `2` | `2` |
| `0.1` | `4` | `4` |
| `0.2` | `3` | `3` |

## Axes And Dependents

| Name | Label | Role | Unit |
| --- | --- | --- | --- |
| `bias_v` | Bias | sweep axis | `V` |
| `drive_frequency_ghz` | Drive frequency | sweep axis | `GHz` |
| `signal_db` | Signal magnitude | measured response | `dB` |
| `phase_deg` | Signal phase | measured response | `deg` |

Held condition:

- Readout power: `-22 dBm` (`fixture_declared`)

## Column Validation

- status: `pass`
- declared columns: `bias_v`, `drive_frequency_ghz`, `signal_db`, `phase_deg`
- source columns: `bias_v`, `drive_frequency_ghz`, `signal_db`, `phase_deg`, `operator_note`
- missing declared columns: `none`
- missing shape columns: `none`
- undeclared shape columns: `none`
- extra source columns: `operator_note`

## Plot Candidates

| Kind | X | Series | Y | Source | Boundary note |
| --- | --- | --- | --- | --- | --- |
| `ragged_line_family` | `drive_frequency_ghz` | `bias_v` | `signal_db` | `source/ragged-adaptive-frequency-response.csv` | Plot candidates are declared ragged line-family candidates only; no rendering, fit, uncertainty, or scientific validation is provided. |
| `ragged_line_family` | `drive_frequency_ghz` | `bias_v` | `phase_deg` | `source/ragged-adaptive-frequency-response.csv` | Plot candidates are declared ragged line-family candidates only; no rendering, fit, uncertainty, or scientific validation is provided. |

## Warnings

- `extra_source_column`: source table contains undeclared `operator_note`. It
  is reported but not treated as plot metadata.

## Boundary Notes

- The ragged scan shape comes from fixture declaration, not schema
  inference.
- Variable inner-axis coverage is expected for this fixture and is not
  treated as missing rectangular grid points.
- Plot candidates are declared ragged line-family candidates only; no
  rendering, fit, uncertainty, or scientific validation is provided.
- This fixture validates declared ragged coverage consistency only, not
  scientific correctness.

## Reviewer Questions

A reviewer should be able to answer:

- which axis groups the adaptive scan;
- which inner axis has variable coverage;
- whether each declared group has the expected observed point count;
- which measured responses can become line-family plot candidates;
- what is mechanically checked and what remains unvalidated;
- that this fixture tests model adequacy, not rectangular grid coercion or
  a final storage or plotting API.
