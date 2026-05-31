# Measurement Intent Resolution Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests one narrow measurement-context boundary:

- a measurement intent may carry moving context selectors;
- a run-start resolution receipt freezes those selectors to point-in-time
  context records;
- the resulting measurement record carries only resolved context links;
- context remains optional for measurement-record validity.

The candidate is side-effect free. It does not read primary data, inspect
context payloads, control hardware, write parameters, mutate setup bindings,
sync environments, import code, execute code, restore context, or define a
shared context schema.
