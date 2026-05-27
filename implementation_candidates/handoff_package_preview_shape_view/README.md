# Handoff Package Preview Shape View Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, a final preview schema, plotting layer, dataframe or array API,
storage mapping, importer, GUI contract, or scientific validation model.

It tests whether an already opened handoff package can expose declared preview
plot/view projection facts for reader/GUI use:

- preserve manifest-declared `data_shape` through the read-only opener;
- expose declared preview affordance, axis order, column metadata, and
  normalized preview plot candidate bindings;
- use declared preview-shape fixture cases as input pressure for preview
  affordances, not as package-route support for every fixture case;
- report unsupported preview affordances, plot-kind mismatches, incomplete
  bindings, or bindings that do not match declared metadata as findings;
- keep file reads, trace opening, shape inference, rendering, fitting,
  storage mutation, and package acceptance out of scope.

The candidate consumes declared metadata only. It does not infer shape from CSV
headers, source filenames, trace files, sidecar conventions, or binary
containers.
