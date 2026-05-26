# Expected Fixed-Vector Response Table Shape Review

## Status

Expected reviewer-facing output for the synthetic
`fixed_vector_response_table` fixture. This is not a storage schema,
plotting API, dataframe API, general ndarray API, or product contract.

## Measurement

- measurement: `synthetic-single-shot-iq-001`
- label: `Synthetic Single-Shot IQ`
- target: `readout_resonator`
- source kind: `declared_primary_table`
- source table: `source/single-shot-iq-vector.csv`

## Declared Shape

- kind: `fixed_vector_response_table`
- vector assumption: `fixed_shape_per_row`
- axis order: `pulse_amplitude_v`
- row count: `4`
- duplicate coordinates: `False`
- status: `pass`

## Axes And Vector Responses

| Name | Label | Role | Unit |
| --- | --- | --- | --- |
| `pulse_amplitude_v` | Pulse amplitude | sweep axis | `V` |
| `shot_iq` | Single-shot IQ | vector response | `V` |

Held condition:

- Readout duration: `1600 ns` (`fixture declaration`)

## Column Validation

- status: `pass`
- declared columns: `pulse_amplitude_v`, `shot_iq`, `shot_state`
- source columns: `pulse_amplitude_v`, `shot_iq`, `shot_state`
- missing declared columns: `none`
- missing shape columns: `none`
- undeclared shape columns: `none`
- invalid axis roles: `none`
- invalid vector roles: `none`
- extra source columns: `none`

## Vector Validation

- status: `pass`
- missing vector columns: `none`
- unsupported shape policies: `none`
- unsupported value shapes: `none`

| Column | Shape | Dtype | Components | Reader ndarray shape | Observed lengths | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `shot_iq` | `[2]` | `float64` | `I`, `Q` | `[4, 2]` | `2` | `pass` |

Failed cells:

- `none`

## Plot Candidates

| Kind | Vector column | X component | Y component | Source | Boundary note |
| --- | --- | --- | --- | --- | --- |
| `component_pair_scatter` | `shot_iq` | `I` | `Q` | `source/single-shot-iq-vector.csv` | Plot candidates are declared component-pair candidates only; no rendering, fit, uncertainty, or scientific validation is provided. |

## Warnings

- `none`

## Boundary Notes

- Fixed-vector response shape is declared by fixture metadata, not
  schema inference.
- The reader ndarray shape is a validated convenience view over
  fixed-shape per-row vectors, not a general array-column API.
- Plot candidates are declared component-pair candidates only; no
  rendering, fit, uncertainty, or scientific validation is provided.
- This fixture validates per-row vector parseability, fixed length,
  declared dtype coercion, and coordinate uniqueness only.

## Reviewer Questions

A reviewer should be able to answer:

- which column carries the fixed-shape vector response;
- which components and dtype are declared for the vector values;
- whether every row satisfies the declared vector length;
- which reader ndarray shape can be exposed after validation;
- which conservative component-pair plot candidate is declared;
- that this fixture tests model adequacy, not arbitrary ndarray,
  waveform, matrix heatmap, dataframe, or storage-backend support.
