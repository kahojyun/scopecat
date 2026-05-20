# Selected Run Preview Spike

## Status

Validation spike only. This is not product code, not a plotting API, not a data
schema contract, and not an ADR.

The spike tests whether a selected-run export can expose enough declared table
metadata to produce a tiny plot-spec preview without inferring a general
Scopecat data schema.

## Preview Principle

Declared measurement roles are the current candidate first path for preview.

For this spike, the input says which columns are sweep axes, measured
responses, held conditions, and units. The preview validates declared column
names against the selected source CSV header, carries roles and units as
declared metadata, and then produces a preview table, plot spec, and caption
stub.

The spike does not validate role semantic correctness, unit correctness,
held-condition constancy, numeric suitability, or scientific validity.

Inference is future optional help, not the trust base. Scopecat should not
guess experiment meaning from filenames, nearby notebooks, column names, or
value patterns and then present that guess as authoritative.

Complex scan support should be added as separate fixture cases only when there
is a concrete validation need. The first fixture stays intentionally narrow so
scan declaration design can be validated before a durable recording schema or
API is accepted.

## Scope

Implemented:

- one selected CSV source file;
- declared column roles and units from fixture metadata;
- declared column-name validation against the source CSV header;
- a small preview table;
- plot-spec JSON objects for multiple declared measured responses from the same
  sweep axis;
- a caption stub that remains explicit about missing fit/uncertainty and
  scientific-validation boundaries.

Not implemented:

- plotting or rendered image output;
- dataframe dependencies;
- automatic schema inference;
- scan declaration design beyond the one declared 1D CSV fixture;
- 2D scans, ragged scans, traces, complex arrays, NPZ/HDF5, or backend readers;
- report generation or scientific validation.

Those are future fixture cases, not requirements for this spike.

## Current Fixture Case

- `1d_multi_response`: one sweep axis, one held condition, and multiple
  measured responses from one selected CSV source.

## Future Fixture Cases

Add these only as separate validation questions:

- `2d_grid_csv`: two declared sweep axes and one or more responses;
- `trace_per_point`: a row contains or links to trace-valued data;
- `complex_iq`: declared complex or paired IQ response semantics;
- `ragged_steps`: adaptive or irregular scan steps;
- `npz_companion`: preview data comes from a companion artifact;
- `derived_table`: preview source is derived and must remain distinct from raw
  source data.
