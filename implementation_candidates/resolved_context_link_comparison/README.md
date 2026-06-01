# Resolved Context Link Comparison Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow selected-reference measurement-context boundary:

- compare a current measurement against a user-selected reference measurement;
- compare actual resolved measurement-record context links;
- report same-observed, changed, and missing optional context findings;
- keep measurement intent selectors out of comparison scope;
- keep context payloads, primary data, fit quality, readiness, and cause
  attribution out of scope.

The candidate is side-effect free. It does not read primary data, inspect
context payloads, recursively traverse relation graphs, import linked context,
control hardware, write parameters, mutate setup bindings, sync environments,
import code, execute code, restore context, or define a shared comparison
engine.
