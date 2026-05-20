# Selected Measurement Export Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds the first production-shaped experiment for the preview-ready selected
measurement export slice:

- build a structured selected measurement export summary from explicit input;
- keep the builder side-effect free;
- avoid source-file reads, archive/package writing, GUI, import, plotting, and
  storage identity decisions;
- keep Markdown review rendering in fixture/test support, not in this package.

The package exists to test whether the current fixture-backed boundary can be
expressed cleanly as code. It should not be treated as a final module layout,
domain schema, export contract, or storage model.
