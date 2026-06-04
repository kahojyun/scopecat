# Complex Response Boundary

## Status

Architecture boundary.

Decision status: accepted for current scan/data-shape validation.

This note defines complex-valued responses as logical value metadata over
declared previewable data items. It does not define a primitive complex storage
type, native backend mapping, transform engine, plotting API, dataframe API,
array API, trace complex response schema, matrix preview model, or public
report format.

## Boundary

Scopecat should treat `complex64` and `complex128` as logical value types, not
as primitive storage types in the table model.

A complex-valued response needs two separate facts:

- how the value is stored, such as split scalar columns, a fixed-vector
  `[real, imag]` or `[I, Q]` value, or a future backend-native complex value;
- what the value means, including logical type, representation, real component,
  imaginary component, derived component views, and phase unit.

The current validated slice supports only a fixed-vector cartesian
representation:

- `logical_value.type`: `complex64` or `complex128`;
- `complex64` over `float32` vector storage and `complex128` over `float64`
  vector storage;
- `logical_value.representation`: `cartesian_vector`;
- `value_shape`: `[2]`;
- two declared components, such as `I` and `Q`;
- declared mapping from real and imaginary components to those stored
  components;
- derived views limited to `real`, `imag`, `magnitude`, and `phase`;
- `phase_unit`: `rad`.

## Implications

The complex fixed-vector fixture demonstrates that Scopecat can declare
metadata for real/imag/magnitude/phase views without storing additional
columns, evaluating those views, accepting arbitrary transforms, or making
complex a primitive storage type.

Trace rows may later support complex-valued responses, but trace support should
be validated as trace-schema metadata, not by embedding the fixed-vector table
model inside trace records.

QST/QPT matrices and other complex matrices remain analysis artifacts unless a
future matrix-specific preview model earns row axis, column axis, value
component, basis, source relation, and scan coordinate semantics.

## Decisions Not Earned

This boundary does not accept:

- primitive complex storage in the Scopecat table model;
- native backend complex mapping;
- general conversion or expression evaluation;
- arbitrary fixed-vector semantic types;
- complex trace response support;
- matrix heatmap support for QST/QPT;
- generic ndarray or array-valued response support;
- publication-grade plotting;
- public/export report behavior.
