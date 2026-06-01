# Measurement Context Link Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow measurement-context boundary:

- a measurement record may have zero context links;
- a measurement record may carry resolved context links;
- a measurement record may report missing optional context;
- context links stay reference-only and do not become primary measurement data;
- missing context does not invalidate the measurement record.

The candidate is side-effect free. It does not read primary data, inspect
context payloads, recursively traverse relation graphs, import linked context,
control hardware, write parameters, mutate setup bindings, sync environments,
import code, execute code, restore context, or define a shared context schema.
