# Handoff Package Visual Review Validation Result

## Status

Implementation candidate validated.

This result validates a plot-first local review view model over the read-only
handoff package read view. It is not accepted architecture, a GUI contract, a
rendered plotting surface, a dataframe adapter, final SDK, package import
flow, archive format, package-integrity contract, or shared measurement model.

Artifact posture: `review_summary`. The visual review model is a local
reviewer projection over an opened package; it is not part of the portable
handoff package contract.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_opener/basic_package/`](../../tests/fixtures/handoff_package_opener/basic_package/)

Implementation candidate:
[`../../implementation_candidates/handoff_package_visual_review/`](../../implementation_candidates/handoff_package_visual_review/)

The candidate reuses the existing directory-shaped package fixture and opens
it through the validated read-view path.

## What This Earned

The visual review model shows that an opened handoff package can be projected
into a plot-first review surface:

- place declared plot summaries before table drilldown facts;
- expose axis name, label, unit, and role as structured facts;
- expose local plot points without selecting a plotting library;
- keep measurement label, experiment type, target, table row counts, linked
  context references, and review findings next to the visual summary;
- keep table facts available as drilldown summaries rather than making tables
  the first review surface;
- report measurements with no declared plot candidates as explicit review
  attention instead of producing a blank surface without explanation;
- preserve duplicate declared plot candidates as separate positioned visual
  summaries while flagging duplicates for review;
- reject read-view drift where a declared plot axis lacks corresponding axis
  metadata instead of inventing labels or roles;
- represent caption-like context as structured fields instead of natural
  language caption text.

## Boundary

This candidate does not:

- render plots or choose matplotlib, Plotly, Qt, web, notebook, or any other
  visual toolkit;
- generate caption prose or accept natural-language caption text as a
  contract;
- define GUI components, layout, interactions, or navigation;
- define stable public Python SDK names or dataframe conversion behavior;
- accept, import, organize, archive, copy, move, or write package contents;
- mutate local Scopecat storage;
- validate package integrity, signatures, checksums, or archive contents;
- infer data schema, scalar types, plot candidates, or scientific meaning;
- recursively traverse linked context or package relations;
- promote a shared measurement-record domain model.

## Result

The open-before-import route now has a view-model candidate for the way many
experimental users naturally inspect packages: start with plots and structured
context, then drill into tables or raw package data only when needed.

This is different from the read-view candidate, which answers whether code can
open the package and access table/plot objects. The visual review candidate
answers how those reader facts can be organized for user review without
building the GUI or committing to a final SDK.
