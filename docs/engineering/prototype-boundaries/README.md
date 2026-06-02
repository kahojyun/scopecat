# Engineering Prototype Boundaries

## Status

Current route-local engineering prototype boundary notes.

## Purpose

This directory records accepted live prototype boundaries: what can live under
`src/scopecat/`, what tests must protect, and what remains outside scope.

These notes are not final product architecture, public API commitments, or
production vertical-slice acceptance. Start from
[`../capability-register.md`](../capability-register.md) to find the
active capability and implementation owner, then open the boundary note listed
here and the owning module README for API details.

## Prototype Boundaries

| Boundary | Use For |
| --- | --- |
| [`environment-operation.md`](environment-operation.md) | Approved local `uv` execution/review/probe vertical. |
| [`handoff.md`](handoff.md) | Handoff package writer, reader, local review, receiving gate, import plan, and durable-import adapter boundary. |
| [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) | First durable handoff import/storage mutation through Measurement Records. |
| [`measurement-records-creation-lifecycle.md`](measurement-records-creation-lifecycle.md) | Durable Measurement Records creation, writer/read/finalization/read-model lifecycle. |
| [`measurement-records-legacy-run-storage.md`](measurement-records-legacy-run-storage.md) | Legacy run storage visibility, converted-primary attach, references, inventory, and local review. |
| [`parameter-state.md`](parameter-state.md) | Parameter-state review, storage/read view, selection context, and route-local pre-run consumption. |
