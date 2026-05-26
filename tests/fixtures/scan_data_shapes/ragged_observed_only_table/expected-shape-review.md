# Expected Observed-Only Ragged Table Shape Review

## Status

Expected reviewer-facing output for the synthetic
`ragged_observed_only_table` fixture. This is not a storage schema,
plotting API, file importer, or product contract.

## Measurement

- measurement: `synthetic-meas-02004`
- label: `qB observed adaptive frequency response`
- target: `qB`
- source kind: `primary_measurement`
- source table: `source/ragged-observed-frequency-response.csv`

## Declared Shape

- kind: `ragged_observed_only_table`
- coverage policy: `observed_only`
- axis order: `bias_v`, `drive_frequency_ghz`
- grouping axis: `bias_v`
- ragged axis: `drive_frequency_ghz`
- total row count: `10`
- status: `pass`

Observed group coverage:

| Group | Observed points |
| --- | --- |
| `-0.1` | `3` |
| `0.0` | `5` |
| `0.1` | `2` |

## Axes And Dependents

| Name | Label | Role | Unit |
| --- | --- | --- | --- |
| `bias_v` | Bias | sweep axis | `V` |
| `drive_frequency_ghz` | Drive frequency | sweep axis | `GHz` |
| `signal_db` | Signal magnitude | measured response | `dB` |
| `phase_deg` | Signal phase | measured response | `deg` |

Held condition:

- Readout power: `-24 dBm` (`fixture_declared`)

## Column Validation

- status: `pass`
- declared columns: `bias_v`, `drive_frequency_ghz`, `signal_db`, `phase_deg`
- source columns: `bias_v`, `drive_frequency_ghz`, `signal_db`, `phase_deg`
- missing declared columns: `none`
- missing shape columns: `none`
- undeclared shape columns: `none`
- extra source columns: `none`

## Plot Candidates

| Kind | X | Series | Y | Source | Boundary note |
| --- | --- | --- | --- | --- | --- |
| `ragged_observed_line_family` | `drive_frequency_ghz` | `bias_v` | `signal_db` | `source/ragged-observed-frequency-response.csv` | Plot candidates are declared observed ragged line-family candidates only; no rendering, fit, uncertainty, or scientific validation is provided. |
| `ragged_observed_line_family` | `drive_frequency_ghz` | `bias_v` | `phase_deg` | `source/ragged-observed-frequency-response.csv` | Plot candidates are declared observed ragged line-family candidates only; no rendering, fit, uncertainty, or scientific validation is provided. |

## Warnings

- `none`

## Boundary Notes

- Observed-only ragged coverage is summarized from the fixture table
  after acquisition.
- No expected group point counts are declared, so completeness against a
  planned adaptive path is not claimed.
- Plot candidates are declared observed ragged line-family candidates
  only; no rendering, fit, uncertainty, or scientific validation is
  provided.
- This fixture validates observed coordinate uniqueness and declared
  column presence only, not scientific correctness.

## Reviewer Questions

A reviewer should be able to answer:

- which groups were observed in the completed adaptive scan;
- how many points each observed group contains;
- which inner axis has variable coverage;
- which measured responses can become line-family plot candidates;
- that completeness against planned group counts is not claimed;
- that this fixture tests model adequacy, not adaptive planner semantics
  or a final storage or plotting API.
