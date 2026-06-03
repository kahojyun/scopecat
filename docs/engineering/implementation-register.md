# Implementation Register

## Status

Current implementation ownership register.

## Purpose

Track live implementation owners and point to the nearest detailed owner for
APIs, artifact boundaries, scope boundaries, tests, and fixtures. This is an
engineering owner index, not a target capability map, adoption strategy,
brownfield migration document, test inventory, or second module README.

## Implementation Owners

| Implementation Owner | Product Capability | Owns | Primary Detail Owner |
| --- | --- | --- | --- |
| `scopecat.measurement_records` | CAP-001 | Durable local Measurement Records storage, read/update/import, references, inventory, and local review. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`measurement-records-creation-lifecycle.md`](prototype-boundaries/measurement-records-creation-lifecycle.md), [`measurement-records-legacy-run-storage.md`](prototype-boundaries/measurement-records-legacy-run-storage.md) |
| `scopecat.handoff` | CAP-002 | Scopecat-authored package writing/opening/preview, receiving gate, import plan, and durable-import adaptation. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md), [`handoff.md`](prototype-boundaries/handoff.md), [`handoff-durable-import-storage.md`](prototype-boundaries/handoff-durable-import-storage.md) |
| `scopecat.environment_operation` | CAP-004 | Approved local `uv sync` execution, typed result/review records, bounded runtime probe, and route-level operation composition. | [`src/scopecat/environment_operation/README.md`](../../src/scopecat/environment_operation/README.md), [`environment-operation.md`](prototype-boundaries/environment-operation.md) |
| `scopecat.parameter_state` | CAP-003 | Adapter-authored review, storage/read view, source-agnostic projection, selection, and route-local manual pre-run review chain. | [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md), [`parameter-state.md`](prototype-boundaries/parameter-state.md) |

## Update Rule

Update this register when live code:

- adds or retires an implementation owner;
- changes which module owns an API family, artifact authority, test/fixture
  orientation, or boundary note;
- promotes a use case, scenario, operation, workflow step, or seam into live
  route-local code;
- supersedes a historical candidate path.

Do not copy product capability strategy here. Keep detailed test and fixture
orientation in module READMEs unless ownership changes.
