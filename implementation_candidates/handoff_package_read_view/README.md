# Handoff Package Read View Candidate

This package is an implementation candidate, not accepted Scopecat
architecture or a stable SDK.

It tests a reader-facing object shape over the validated read-only handoff
package opener:

- open a directory-shaped package through the existing opener;
- expose package metadata and selected measurements as small read objects;
- let a user look up a measurement by `measurement_record_id`;
- expose primary CSV data and declared preview rows as rectangular
  string-valued table-like objects;
- expose declared plot candidates as copy-safe point series;
- expose copy-safe declared preview shape and plot-candidate metadata for
  downstream review projections;
- keep linked context reference-only and findings visible.

This is a use-case prototype for how a Python SDK or GUI model might feel. It
is a local/internal validation read surface, not a portable/export artifact.
It does not add a dataframe dependency, infer types, define final API names,
accept/import packages, mutate storage, extract archives, validate package
integrity, define a GUI, or promote a shared measurement-record domain model.
