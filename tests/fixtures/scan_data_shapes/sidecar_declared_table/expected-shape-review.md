# Expected Sidecar-Declared Table Shape Review

## Status

Expected reviewer-facing output for the synthetic `sidecar_declared_table`
fixture. This is not a storage schema, sidecar importer, plotting API, or
product contract.

## Measurement

- measurement: `synthetic-meas-02002`
- label: `qA sidecar-declared Rabi scan`
- target: `qA`
- source kind: `imported_legacy_source`
- source table: `source/sidecar-declared-rabi-table.csv`
- metadata source: `sidecar_declaration`

## Declared Shape

- kind: `sidecar_declared_table`
- table shape: `1d_table`
- axis order: `drive_amp`
- row count: `3`
- status: `pass`

## Column Mapping

| Physical column | Declared name | Label | Role | Unit |
| --- | --- | --- | --- | --- |
| `c0` | `drive_amp` | Drive amplitude | sweep axis | `arb` |
| `c1` | `p_excited` | Excited-state probability | measured response | `probability` |
| `c2` | `shot_count` | Shot count | supporting count | `count` |

Held condition:

- Bias: `0.100 V` (`sidecar_declared`)

## Column Validation

- status: `pass`
- physical columns: `c0`, `c1`, `c2`
- declared names: `drive_amp`, `p_excited`, `shot_count`
- missing physical columns: `none`
- unmapped physical columns: `none`

## Plot Candidates

| X | Y | Source | Metadata source | Boundary note |
| --- | --- | --- | --- | --- |
| `drive_amp` | `p_excited` | `source/sidecar-declared-rabi-table.csv` | sidecar_declaration | Plot candidates use sidecar-declared column meaning; no source-header inference, fit, uncertainty, or scientific validation is provided. |

## Warnings

- `legacy_source_weak_labels`: source table uses weak physical column names;
  sidecar metadata is required for interpretation.

## Boundary Notes

- Column meaning comes from sidecar declaration, not source header inference.
- Plot candidates use sidecar-declared column meaning; no source-header
  inference, fit, uncertainty, or scientific validation is provided.
- This fixture validates mapping consistency only, not semantic correctness
  or scientific validity.

## Reviewer Questions

A reviewer should be able to answer:

- which physical columns map to meaningful declared names;
- which metadata came from the sidecar declaration;
- which axis and response can become a plot candidate;
- whether the source table is weakly labeled;
- what is mechanically checked and what remains unvalidated;
- that this fixture tests model adequacy, not a sidecar importer or schema
  inference engine.
