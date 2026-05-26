# Scan Data Shape Validation Result

## Status

Spike fixtures validated.

This result validates a narrow Measurement Records support slice:
**Declared Scan/Data-Shape Fixtures**.

It does not accept a final data-shape schema, storage layout, native nested
storage mapping, dataframe or array API, plotting layer, importer, schema
inference engine, binary container format, hardware-control behavior, or
scientific validation model.

## Fixtures

Fixture root:
[`../../tests/fixtures/scan_data_shapes/`](../../tests/fixtures/scan_data_shapes/)

Generator spike:
[`../../spikes/scan_data_shapes/`](../../spikes/scan_data_shapes/)

Artifact posture:

- `expected-shape-summary.json` files are `internal_validation_summary`
  artifacts.
- `expected-shape-review.md` files are `review_summary` artifacts.
- Neither expected output is a portable export/package artifact or public
  report.

Current fixture pressures:

- rectangular 2D grid table;
- declared ragged/adaptive table with expected group counts;
- observed-only ragged/adaptive table when expected group counts are unknown;
- trace-per-point table with fixture-relative trace CSV references;
- fixed-vector response table for compact fixed-shape per-row single-shot
  values;
- complex fixed-vector response table for cartesian logical complex values;
- sidecar-declared weak 1D table pressure.

All fixtures are synthetic and repository-safe. They intentionally use small
CSV files and explicit declarations rather than legacy parsing, notebook
inspection, or source-header inference.

## What This Earned

The spike shows that Scopecat can describe several preview-relevant
measurement data shapes with an explicit semantic envelope before choosing a
storage backend or plotting implementation:

- rectangular grid declarations can state axes, expected cardinality, measured
  responses, extra source columns, and 2D plot candidates;
- ragged/adaptive declarations can state grouping axis, variable inner axis,
  expected group counts, unexpected or missing groups, and line-family plot
  candidates without coercing the data into a rectangular grid;
- observed-only ragged declarations can report completed adaptive coverage
  without claiming completeness against a planned path;
- trace-per-point declarations can bind outer scan coordinates to
  fixture-relative trace tables, validate reference shape and containment,
  summarize trace row counts, and describe trace-family plot candidates;
- fixed-vector declarations can validate small fixed-shape per-row vector
  values against declared `value_shape`, `dtype`, and `shape_policy`, then
  report a reader ndarray-shaped convenience view without accepting a general
  array API;
- complex fixed-vector declarations can add logical value metadata for
  `complex64` or `complex128` cartesian values and declare real, imaginary,
  magnitude, and phase views without accepting a primitive complex storage
  type or general transform engine;
- sidecar declarations can assign meaning to weak physical columns without
  trusting source headers as the semantic authority.

The useful common idea is **declared preview metadata**: shape kind, axes,
roles, labels, units, row or group counts, trace references, and plot-candidate
descriptions supplied explicitly enough to support review without automatic
schema inference.

## Boundary

This slice validates concept and fixture adequacy only.

It does not:

- define final storage tables, nested records, object IDs, or backend layout;
- require or reject native `list`, `struct`, array, HDF5, Zarr, Arrow, or
  similar storage capabilities;
- define a stable reader API, dataframe adapter, array API, or query model;
- render plots, align traces, resample traces, fit data, or judge waveform
  quality;
- import legacy formats or infer shape from notebooks, filenames, source
  headers, sidecar conventions, or binary containers;
- validate unit semantics, instrument calibration, reproducibility, or
  scientific correctness;
- control hardware, execute scans, or model adaptive planner decisions;
- promote fixture-local field names into a shared product schema.

The trace-per-point fixture is still concept validation even if future storage
natively supports lists or structs. Native nested storage can hold richer
values, but Scopecat still needs explicit metadata to answer what each axis,
response, trace reference, completeness claim, and preview candidate means.

The fixed-vector fixture is also concept validation. It validates a narrow
small-vector contract for compact per-row responses, such as an IQ pair. It
does not accept arbitrary ndarray columns, large waveforms, image-like arrays,
matrix heatmaps, QST/QPT support, or pandas-like multi-index table behavior.

The complex fixed-vector fixture is concept validation for logical value
metadata only. It validates a cartesian vector representation and derived view
declarations, not native complex storage, arbitrary conversion, trace complex
schema, or matrix complex analysis support.

Artifact visualization remains separately bounded in
[`artifact-preview-boundary.md`](artifact-preview-boundary.md): arbitrary
artifacts are stored or referenced by default, and only declared
Scopecat-understood preview models should produce plot candidates.
Complex response semantics are separately bounded in
[`complex-response-boundary.md`](complex-response-boundary.md).

## Result

Scan/data-shape work is ready to serve as pressure evidence for preview-ready
measurement records, import/export review, handoff package inspection, running
inspection, and future storage design. The current evidence favors keeping
shape semantics explicit and storage-independent until repeated consumers need
the same durable contract.

The spike should remain separate from measurement storage writers, handoff
package contracts, import acceptance, plotting, and legacy adapter behavior.
Those slices may reuse the vocabulary only when their authority and artifact
boundaries match.

The current decision summary is
[`scan-data-shape-decision-summary.md`](scan-data-shape-decision-summary.md).
It closes the current shape-expansion phase and recommends moving next to a
consumer of declared preview metadata rather than adding more shape variants.

## Follow-Up

Stop this checkpoint at concept validation unless the next workflow needs a
specific consumer of the shape metadata.

Likely follow-up slices should stay separate:

- trace fixture hardening for duplicate trace references, missing trace files,
  duplicate outer coordinates, or additional containment cases;
- adapter-authored versions of harder shapes, without making legacy readers
  part of Scopecat core;
- matrix heatmap analysis preview for QST/QPT-like outputs, only after a
  matrix-specific table model earns its semantics;
- complex trace response support, only after trace-specific metadata earns its
  semantics;
- preview compatibility findings across selected measurements, without
  accepting raw-data comparison or publication-grade plotting;
- storage-backend mapping experiments, after shape vocabulary has repeated
  consumers and still without treating fixture JSON as final schema.
