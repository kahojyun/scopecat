# Implementation Register

## Status

Current implementation ownership register.

## Purpose

Track live implementation owners and point to the nearest detailed owner for
APIs, tests, fixtures, artifact boundaries, and scope boundaries. This is an
engineering owner index, not a product capability map, adoption model, or
second module README.

Use this document with:

- [`../product/capability-map.md`](../product/capability-map.md) for product
  capability maturity;
- [`workflow-validation-map.md`](workflow-validation-map.md) for workflow seams
  and validation questions;
- [`prototype-boundaries/README.md`](prototype-boundaries/README.md) for
  route-local engineering prototype boundaries.

## Implementation Owners

| Implementation Owner | Product Capability | Maturity | Owns | Primary Detail Owner | Tests And Fixtures Owner |
| --- | --- | --- | --- | --- | --- |
| `scopecat.measurement_records` | Measurement Records | Engineering prototype | Durable record creation, primary-data write/read/finalization, durable import, legacy-run storage visibility, references, inventory, and local review. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`measurement-records-creation-lifecycle.md`](prototype-boundaries/measurement-records-creation-lifecycle.md), [`measurement-records-legacy-run-storage.md`](prototype-boundaries/measurement-records-legacy-run-storage.md) | Module README and matching `tests/` fixture families. |
| `scopecat.handoff` | Handoff Packages | Engineering prototype | Scopecat-authored package writing/opening/preview, local inspection, receiving gate, import plan, and durable-import adaptation into Measurement Records. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md), [`handoff.md`](prototype-boundaries/handoff.md), [`handoff-durable-import-storage.md`](prototype-boundaries/handoff-durable-import-storage.md) | Module README and matching `tests/` fixture families. |
| `scopecat.environment_operation` | Environment Operation | Engineering prototype | Approved local `uv sync` execution, typed result/review records, bounded runtime probe, and route-level operation composition. | [`src/scopecat/environment_operation/README.md`](../../src/scopecat/environment_operation/README.md), [`environment-operation.md`](prototype-boundaries/environment-operation.md) | Module README and matching `tests/` fixture families. |
| `scopecat.parameter_state` | Parameter State Review | Engineering prototype | Adapter-authored review, storage/read view, source-agnostic projection, selection, and route-local manual pre-run consumption/review chain. | [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md), [`parameter-state.md`](prototype-boundaries/parameter-state.md) | Module README and matching `tests/` fixture families. |

## Update Rule

Update this register when live code:

- adds or retires an implementation owner;
- changes which module owns an API family, artifact authority, tests,
  fixtures, or boundary note;
- promotes a workflow gap into live route-local code;
- supersedes a historical candidate path.

Do not copy product capability strategy here. Link to
[`../product/capability-map.md`](../product/capability-map.md) instead.
