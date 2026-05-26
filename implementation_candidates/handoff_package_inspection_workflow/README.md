# Handoff Package Inspection Workflow Candidate

This candidate is not accepted Scopecat architecture, a GUI framework, a
package import flow, a dataframe adapter, or a stable SDK.

It tests whether the current read-only receiving-side handoff package route can
serve as one natural inspection workflow:

- consume a caller-provided directory-shaped handoff package;
- reuse the read-only opener path, including manifest-preview validation;
- expose reader-facing measurement ids, linked context, and findings;
- project the opened package into the plot-first visual-review model;
- write one local static HTML review artifact outside the package tree;
- return a local inspection receipt for the performed steps.

The workflow is local/review-only. It does not accept or import the package
into Scopecat storage, mutate measurement storage, create or extract archives,
claim checksum/signature verification, infer schemas, choose a production GUI
framework, define dataframe behavior, or promote final SDK names.
