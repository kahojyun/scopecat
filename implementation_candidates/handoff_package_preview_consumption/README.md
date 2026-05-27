# Handoff Package Preview Consumption Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, a final SDK, GUI contract, plotting layer, dataframe API,
importer, storage model, or package format.

It tests whether a handoff package can be opened read-only and projected into
one preview-aware local consumption receipt:

- open the package through the read-only handoff package read view;
- compose declared preview-shape projection with the plot-first visual-review
  projection;
- report which first review/use surface is available for each measurement;
- project table drilldown summary facts while keeping SDK and dataframe
  adapters uninvoked;
- keep rendering, GUI components, package acceptance, storage mutation,
  archive handling, package integrity verification, schema inference, and
  scan-shape inference out of scope.

The candidate is a composition slice. It should not redefine preview-shape
contracts, visual-review facts, table APIs, or package opening behavior.
