# Expected Fixed-Vector Response Table Shape Review

## Status

Expected reviewer-facing output for the synthetic
`complex_fixed_vector_response_table` fixture. This is not a storage schema,
plotting API, dataframe API, general ndarray API, or product contract.

## Measurement

- measurement: `synthetic-complex-iq-001`
- label: `Synthetic Complex IQ`
- target: `readout_resonator`
- source kind: `declared_primary_table`
- source table: `source/complex-iq-vector.csv`

## Declared Shape

- kind: `complex_fixed_vector_response_table`
- vector assumption: `fixed_shape_per_row`
- axis order: `readout_power_dbm`
- row count: `4`
- duplicate coordinates: `False`
- status: `pass`

## Axes And Vector Responses

| Name | Label | Role | Unit |
| --- | --- | --- | --- |
| `readout_power_dbm` | Readout power | sweep axis | `dBm` |
| `iq_v` | IQ response | vector response | `V` |

Held condition:

- Readout frequency: `6.250 GHz` (`fixture declaration`)

## Column Validation

- status: `pass`
- declared columns: `readout_power_dbm`, `iq_v`
- source columns: `readout_power_dbm`, `iq_v`
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
- unsupported dtypes: `none`
- unsupported components: `none`
- unsupported complex logical values: `none`

| Column | Shape | Dtype | Components | Reader ndarray shape | Observed lengths | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `iq_v` | `[2]` | `float64` | `I`, `Q` | `[4, 2]` | `2` | `pass` |

Failed cells:

- `none`

## Logical Value Views

| Column | Logical type | Representation | Real component | Imag component | Derived views | Phase unit |
| --- | --- | --- | --- | --- | --- | --- |
| `iq_v` | `complex128` | `cartesian_vector` | `I` | `Q` | `real`, `imag`, `magnitude`, `phase` | `rad` |

## Plot Candidates

| Kind | Vector column | X component | Y component | Source | Boundary note |
| --- | --- | --- | --- | --- | --- |
| `complex_component_pair_scatter` | `iq_v` | `I` | `Q` | `source/complex-iq-vector.csv` | Plot candidates are declared component-pair candidates only; logical complex metadata declares real, imaginary, magnitude, and phase views without earning a primitive complex storage type or transform engine. |

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
