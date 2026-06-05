# Engineering Prototype Boundaries

## Status

Current route-local engineering prototype boundary notes.

## Purpose

This directory records accepted live prototype boundaries: what can live under
`src/scopecat/`, what tests must protect, and what remains outside scope.

Start from [`../implementation-register.md`](../implementation-register.md) to
find the active implementation owner, then open the boundary note listed here
and the owning module README for API details. Use
[`../../product/target-capabilities.md`](../../product/target-capabilities.md) for
product capability maturity.

## Prototype Boundaries

| Boundary | Use For |
| --- | --- |
| [`handoff.md`](handoff.md) | Handoff package writer, reader, local review, receiving gate, import plan, and durable-import adapter boundary. |
| [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) | Current handoff durable-import adaptation into Measurement Records. |
| [`measurement-records-creation-lifecycle.md`](measurement-records-creation-lifecycle.md) | Current durable Measurement Records storage, read/import, and reference boundary. |
| [`measurement-records-legacy-run-storage.md`](measurement-records-legacy-run-storage.md) | Legacy run storage, converted-primary attach, and references. |

These notes are not final product architecture, public API commitments, or
production vertical-slice acceptance.
