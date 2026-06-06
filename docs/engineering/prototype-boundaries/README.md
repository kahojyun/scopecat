# Engineering Prototype Boundaries

## Status

Current implementation-owner engineering prototype boundary notes.

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
| [`handoff.md`](handoff.md) | Handoff package writer, reader, local review, receiving gate, and non-mutating import-plan boundary. |
| [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) | Handoff durable-import adapter boundary into Measurement Records. |
| [`measurement-records-storage.md`](measurement-records-storage.md) | Durable Measurement Records storage, adoption/import/open-by-id, references, read models, and handoff projection boundary. |

These notes are not final product architecture, public API commitments, or
production vertical-slice acceptance.
