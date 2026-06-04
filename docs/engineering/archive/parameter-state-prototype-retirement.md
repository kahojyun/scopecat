# Parameter-State Prototype Retirement

## Status

Retired from active implementation.

## Decision

The former `scopecat.parameter_state` prototype, focused tests, and fixtures
were removed from active code. Git history remains the source for the full
implementation record.

## Reason

The prototype was introduced before a real retained journey or brownfield
entrypoint had earned the boundary. Its code and fixtures overfit discovery
slice handoffs: adapter-specific provenance shaped durable storage, intermediate
fixtures became sources of truth, and later source-agnostic/prepared-run
projections implied ownership that the active product flow had not earned.

## Retained Concepts

Future work may still use these domain concepts when a real journey needs them:

- parameter state;
- parameter entry;
- reviewed parameter snapshot;
- parameter lineage and target scope;
- provenance;
- normalized storage as the intended boundary if managed parameter state is
  promoted again.

Future implementation should restart from the relevant brownfield entrypoint
and current domain model instead of reusing the retired prototype shape.
