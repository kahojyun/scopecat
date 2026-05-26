# Handoff Package SDK View Model Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, a final public SDK, a dataframe dependency decision, GUI
component model, fitting engine, archive format, writable analysis package, or
shared measurement schema.

It tests whether the current read-only handoff package route can be consumed
through a small Python-facing object model:

- open a directory-shaped handoff package through the validated read view;
- access measurements by record id or position index;
- expose primary and preview tables with string-key and position column access;
- expose optional `to_pandas()` and `to_numpy()` adapters without making pandas
  or numpy required dependencies for this research repo;
- expose primary and saved plot specs with axis label/unit/role metadata;
- keep findings and linked context visible for notebook or GUI review.

The candidate keeps writes out of scope. Analysis and fit results are reserved
as future read-only package artifacts or sidecars; this slice does not execute
fit code, infer schemas or scan/data-shape semantics, render GUI plots, mutate
packages, or import accepted records.
