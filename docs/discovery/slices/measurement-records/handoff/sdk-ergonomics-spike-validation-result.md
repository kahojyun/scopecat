# Handoff Package SDK Ergonomics Spike Validation Result

## Status

Script-shaped fixture pressure validated.

Document role: historical discovery validation result. It records what this
slice earned and what it did not establish. Current handoff implementation
boundaries are owned by
[`handoff.md`](../../../../architecture/boundaries/handoff.md);
do not update this result to mirror live API or route changes.

This result validates notebook-style use of the existing handoff package SDK
view model. It is not accepted Scopecat architecture, a final public SDK, a
hard pandas/numpy dependency, plotting library, fitting engine, writable
analysis model, import flow, storage model, package format, or shared
measurement-record schema.

Artifact posture: `internal_validation_summary`. The test is repository-safe
ergonomics pressure over local read-only package objects; it is not a portable
package artifact, public report, or generated user notebook.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_route_pressure/richer_reader_package/`](../../../../../tests/fixtures/handoff_package_route_pressure/richer_reader_package)

Test:
[`../../tests/test_handoff_package_sdk_ergonomics_spike.py`](../../../../../tests/test_handoff_package_sdk_ergonomics_spike.py)

Implementation candidate consumed:
[`../../implementation_candidates/handoff_package_sdk_view_model/`](../../../../../implementation_candidates/handoff_package_sdk_view_model)

The spike uses the richer route-pressure package rather than another
single-measurement package. It simulates a notebook/script flow with fake
pandas and numpy modules so the repository does not add hard dataframe or
array dependencies.

## What This Earned

The SDK view model supported the first notebook-style handoff use case:

- open a package and discover measurement ids in package order;
- access measurements by id or position;
- convert primary tables to pandas-like frames with column order and Scopecat
  metadata in `attrs`;
- access multi-plot measurements as declared saved plot specs and convert each
  plot to pandas-like records or numpy-like arrays;
- keep table-only measurements usable through dataframe-first table access
  instead of forcing every measurement to have a primary plot;
- keep linked-context findings visible next to measurement data;
- keep fit and analysis result collections as empty read-only extension points;
- keep package acceptance, writeback, plotting, fitting, schema inference, and
  scan-shape inference out of the notebook path.

This matches the expected lab notebook path: users commonly move from tabular
data into dataframe-like objects, plot-ready arrays, and downstream fitting
code. The spike validates that Scopecat can provide those inputs without
owning fitting or plotting yet.

## Boundary

This spike does not:

- rename or finalize public SDK objects;
- add pandas, numpy, matplotlib, scipy, or lmfit as dependencies;
- coerce dataframe dtypes, infer numeric units, or infer scalar types;
- render plots, choose a plotting library, or generate matplotlib code;
- execute fits, select ROIs, reject outliers, or validate scientific results;
- write analysis results back into a package or local storage;
- accept/import packages, mutate storage, observe package integrity, or
  traverse linked-context payloads;
- promote scan/data-shape metadata into the SDK surface.

## Result

At this checkpoint, the handoff route had notebook-oriented pressure beyond
object-level SDK unit tests. A user could naturally open a handoff package,
discover measurements, get dataframe-like tables, get plot-ready
records/arrays, and keep contextual review findings visible without requiring
package import or final GUI/plotting decisions.

Further SDK work should require a concrete missing notebook action, such as
numeric dtype conversion, a chosen plotting helper, or read-only analysis
result display. Those should remain separate from import/storage and GUI
implementation work.
