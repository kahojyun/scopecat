# Architecture Boundaries

## Status

Accepted implementation-boundary notes, not public user documentation.

## Purpose

This directory owns current architecture decisions for live route-local
engineering boundaries. Start from
[`../../engineering/vertical-slice-register.md`](../../engineering/vertical-slice-register.md)
to find the active slice, then open the boundary note listed here and the
owning module README for API details.

## Current Boundaries

| Boundary | Use For |
| --- | --- |
| [`environment-operation.md`](environment-operation.md) | Approved local `uv` execution/review/probe vertical. |
| [`handoff.md`](handoff.md) | Handoff package writer, reader, local review, receiving gate, import plan, and durable-import adapter boundary. |
| [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) | First durable handoff import/storage mutation through Measurement Records. |
| [`measurement-records-creation-lifecycle.md`](measurement-records-creation-lifecycle.md) | Durable Measurement Records creation, writer/read/finalization/read-model lifecycle. |
| [`measurement-records-legacy-run-storage.md`](measurement-records-legacy-run-storage.md) | Legacy run storage visibility, converted-primary attach, references, inventory, and local review. |
| [`parameter-state.md`](parameter-state.md) | Parameter-state review, storage/read view, selection context, and route-local pre-run consumption. |
