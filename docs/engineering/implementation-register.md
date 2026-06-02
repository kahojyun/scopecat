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

| Implementation Owner | Product Capability | Owns | Primary Detail Owner | Tests And Fixtures |
| --- | --- | --- | --- | --- |
| `scopecat.measurement_records` | Measurement Records | Durable local Measurement Records storage, read/update/import, references, inventory, and local review. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`measurement-records-creation-lifecycle.md`](prototype-boundaries/measurement-records-creation-lifecycle.md), [`measurement-records-legacy-run-storage.md`](prototype-boundaries/measurement-records-legacy-run-storage.md) | [`tests/prototypes/measurement_records/`](../../tests/prototypes/measurement_records/), selected fixtures under [`tests/fixtures/`](../../tests/fixtures/) such as `normalized_primary_table/`, `existing_record_update/`, `running_measurement_inspection/`, and legacy families. |
| `scopecat.handoff` | Handoff Packages | Scopecat-authored package writing/opening/preview, receiving gate, import plan, and durable-import adaptation. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md), [`handoff.md`](prototype-boundaries/handoff.md), [`handoff-durable-import-storage.md`](prototype-boundaries/handoff-durable-import-storage.md) | [`tests/prototypes/handoff/`](../../tests/prototypes/handoff/), fixtures under [`tests/fixtures/prototypes/handoff/`](../../tests/fixtures/prototypes/handoff/) and handoff fixture families. |
| `scopecat.environment_operation` | Environment Operation | Approved local `uv sync` execution, typed result/review records, bounded runtime probe, and route-level operation composition. | [`src/scopecat/environment_operation/README.md`](../../src/scopecat/environment_operation/README.md), [`environment-operation.md`](prototype-boundaries/environment-operation.md) | [`tests/prototypes/environment_operation/`](../../tests/prototypes/environment_operation/), fixtures under [`tests/fixtures/prototypes/environment_operation/`](../../tests/fixtures/prototypes/environment_operation/) and environment fixture families. |
| `scopecat.parameter_state` | Parameter State Review | Adapter-authored review, storage/read view, source-agnostic projection, selection, and route-local manual pre-run review chain. | [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md), [`parameter-state.md`](prototype-boundaries/parameter-state.md) | [`tests/prototypes/parameter_state/`](../../tests/prototypes/parameter_state/), selected parameter-state fixture families under [`tests/fixtures/`](../../tests/fixtures/). |

## Update Rule

Update this register when live code:

- adds or retires an implementation owner;
- changes which module owns an API family, artifact authority, tests,
  fixtures, or boundary note;
- promotes a workflow gap into live route-local code;
- supersedes a historical candidate path.

Do not copy product capability strategy here. Link to
[`../product/capability-map.md`](../product/capability-map.md) instead.
