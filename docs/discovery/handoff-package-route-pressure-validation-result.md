# Handoff Package Route Pressure Validation Result

## Status

Fixture pressure validated.

This result validates richer repository fixtures against the existing
read-only handoff package route. It is not accepted architecture, a new
package format, a final SDK object model, GUI contract, dataframe API,
importer, storage model, scan-shape schema, or shared measurement model.

Artifact posture: `internal_validation_summary`. The fixtures are
repository-safe discovery artifacts; they are not generated portable packages
or public reports.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_route_pressure/`](../../tests/fixtures/handoff_package_route_pressure/)

Tests:
[`../../tests/test_handoff_package_route_pressure_fixture.py`](../../tests/test_handoff_package_route_pressure_fixture.py)

The fixture set adds:

- a two-measurement package with one measurement carrying two declared plot
  candidates over the same primary table;
- a second `preview_ready` measurement with no declared plot candidates, so
  table drilldown becomes the first surface;
- shared visible-but-not-packaged linked context across both measurements;
- a degraded-preview manifest package that can be previewed from manifest
  facts but is rejected by the read-only opener before primary file reads;
- omitted primary digest/size facts to keep optional integrity metadata
  pressure visible on the open/read route.

## What This Earned

The richer fixture shows that the current route handles realistic reader
pressure without adding another product layer:

- the opener accepts missing optional digest/size fields and opens both
  preview-ready measurements;
- the read view exposes multi-plot and no-plot measurements through the same
  table and plot-series objects;
- visual review emits two visual summaries for the multi-plot measurement and
  an explicit no-plot attention item for the table-only measurement;
- preview consumption chooses `plot_first_visual_review` for the multi-plot
  measurement and `table_drilldown` for the no-plot measurement;
- GUI view state projects matching navigation and primary-surface counts;
- contents preview remains the manifest-only surface for degraded preview
  packages, while opener/read-view composition still requires
  `preview_ready` metadata.

## Boundary

This fixture pressure does not:

- add a new implementation candidate or public package contract;
- change writer behavior or require generated fixture output;
- choose a plotting library, GUI component model, or dataframe dependency;
- infer scan shape, schema, scalar types, plot candidates, or scientific
  meaning;
- accept/import packages, mutate storage, observe integrity, extract
  archives, or traverse linked-context payloads;
- promote the route-local read models into a shared measurement-record domain
  model.

## Result

The handoff route no longer depends only on the original one-measurement,
one-plot package fixture for reader-side confidence. The route has enough
fixture pressure to pause broad handoff slice expansion and move future work
toward narrower design decisions: notebook/SDK ergonomics, GUI interaction
details, or import/storage questions only when a concrete workflow requires
them.
