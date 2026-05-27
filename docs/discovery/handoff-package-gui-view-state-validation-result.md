# Handoff Package GUI View-State Validation Result

## Status

Implementation candidate validated.

This result validates a narrow local GUI-ready view-state projection over
existing read-only handoff package projections. It is not accepted Scopecat
architecture, a live GUI framework, final GUI contract, plotting library,
stable SDK, dataframe API, importer, storage model, package format, or shared
measurement model.

Artifact posture: `review_summary`. The GUI view state is a local review/runtime
projection over an opened package; it is not part of the portable handoff
package contract.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_opener/basic_package/`](../../tests/fixtures/handoff_package_opener/basic_package/)

Implementation candidate:
[`../../implementation_candidates/handoff_package_gui_view_state/`](../../implementation_candidates/handoff_package_gui_view_state/)

The candidate reuses the existing directory-shaped package fixture and
consumes the existing preview-consumption and visual-review projections.

## What This Earned

The GUI view-state model shows that the current read-only handoff package
route can be shaped into local state a future GUI could consume:

- measurement-list navigation;
- deterministic default selection of the first package measurement;
- selected-measurement panels for primary surface, plot summary, table
  drilldown, linked context, and findings;
- primary surface kinds of `plot`, `table_drilldown`, or `review_findings`
  derived from existing preview-consumption first-surface facts;
- plot panel facts from the visual-review model, including visual summary id,
  axis metadata, title-like label, duplicate state, and point count without
  embedding plot points in the GUI state;
- explicit deferred actions for plot rendering, dataframe code, and package
  acceptance.

The candidate validates package id, measurement id, and visual-summary
alignment across the consumed projections before emitting the local view state.

## Boundary

This candidate does not:

- build a live GUI, component tree, router, or interaction model;
- render plots or choose a plotting toolkit;
- define final GUI, SDK, dataframe, or Python package-open APIs;
- invoke dataframe adapters or materialize dataframe objects;
- accept, import, organize, archive, copy, move, or write package contents;
- mutate local Scopecat storage;
- validate package integrity, signatures, checksums, or archive contents;
- infer data schema, scan shape, scalar types, plot candidates, or scientific
  meaning;
- recursively traverse linked context or import linked-context payloads;
- promote a shared measurement-record domain model.

## Result

The handoff route now has a minimal GUI-facing pressure check after route
consolidation. The validated user posture remains plot-first: a future GUI can
start from measurement navigation and a selected-measurement primary surface
without requiring package import, dataframe conversion, or rendering decisions
to be settled first.
