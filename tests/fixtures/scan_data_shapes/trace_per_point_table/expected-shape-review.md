# Expected Trace-Per-Point Table Shape Review

## Status

Expected reviewer-facing output for the synthetic `trace_per_point_table`
fixture. This is not a storage schema, plotting API, file importer,
binary container contract, or product contract.

## Measurement

- measurement: `synthetic-meas-02005`
- label: `qC bias-indexed resonator traces`
- target: `qC`
- source kind: `primary_measurement`
- source table: `source/trace-point-index.csv`

## Declared Shape

- kind: `trace_per_point_table`
- axis order: `bias_v`
- trace ref column: `trace_ref`
- trace independent column: `time_ns`
- trace response column: `signal_v`
- point count: `3`
- duplicate outer coordinates: `False`
- status: `pass`

## Axes And Trace References

| Name | Label | Role | Unit |
| --- | --- | --- | --- |
| `bias_v` | Bias | sweep axis | `V` |
| `trace_ref` | Trace table reference | trace reference | `relative_ref` |

Held condition:

- Readout power: `-26 dBm` (`fixture_declared`)

## Column Validation

- status: `pass`
- declared columns: `bias_v`, `trace_ref`, `trace_kind`
- source columns: `bias_v`, `trace_ref`, `trace_kind`
- missing declared columns: `none`
- missing shape columns: `none`
- undeclared shape columns: `none`
- extra source columns: `none`

## Trace Validation

- status: `pass`
- trace refs: `source/traces/bias-neg-0p1.csv`, `source/traces/bias-0p0.csv`, `source/traces/bias-0p1.csv`
- unsafe trace refs: `none`
- missing trace files: `none`

| Trace ref | Status | Rows | Columns | Missing trace columns |
| --- | --- | --- | --- | --- |
| `source/traces/bias-neg-0p1.csv` | `pass` | `4` | `time_ns`, `signal_v` | `none` |
| `source/traces/bias-0p0.csv` | `pass` | `5` | `time_ns`, `signal_v` | `none` |
| `source/traces/bias-0p1.csv` | `pass` | `3` | `time_ns`, `signal_v` | `none` |

## Plot Candidates

| Kind | X | Series | Y | Trace ref column | Source | Boundary note |
| --- | --- | --- | --- | --- | --- | --- |
| `trace_family` | `time_ns` | `bias_v` | `signal_v` | `trace_ref` | `source/trace-point-index.csv` | Plot candidates are declared trace-family candidates only; no rendering, alignment, resampling, fit, uncertainty, or scientific validation is provided. |

## Warnings

- `none`

## Boundary Notes

- Trace-per-point shape is declared by fixture metadata plus
  package-relative trace references, not schema inference.
- Trace references are checked for fixture-local relative shape and
  openability only; no binary container, storage layout, or importer
  contract is earned.
- Plot candidates are declared trace-family candidates only; no
  rendering, alignment, resampling, fit, uncertainty, or scientific
  validation is provided.
- This fixture validates reference shape, trace openability, trace
  columns, and trace row counts only, not waveform correctness.

## Reviewer Questions

A reviewer should be able to answer:

- which outer coordinate owns each trace reference;
- whether trace references are fixture-local and openable;
- which trace columns define the independent and response values;
- how many rows each trace contains;
- which trace-family plot candidate is declared;
- that this fixture tests model adequacy, not a binary container,
  storage layout, importer, or waveform analysis API.
