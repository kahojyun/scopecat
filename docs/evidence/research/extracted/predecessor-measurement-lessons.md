# Predecessor Measurement Lessons

## Status

Extracted predecessor summary.

## Source

This note distills lessons from the predecessor measurement-system attempt that
was removed from the working tree after extraction on 2026-05-16. Use Git
history only if exact predecessor wording is needed.

## Summary

The predecessor work showed that ordinary Python recording, durable measurement
identity, explicit data shape, checkpoint-safe reads, source identity, and
low-ceremony reopen are important substrates.

It also showed that measurement history alone is too narrow. Scopecat discovery
needs to cover intent, setup, code, calibration, analysis handoff, and bounded
automation pressure without inheriting the predecessor's product order, object
model, personas, UI, or storage sketches.

## Preserved Lessons

- Ordinary Python and notebook-heavy acquisition are important adoption paths.
- Stable run or measurement identity is useful, but users also need selected
  context, companion artifacts, source aliases, lifecycle state, and ambiguity
  warnings.
- Dataset shape pressure includes grids, partial grids, irregular points,
  traces, variable-length records, complex values, IQ arrays, shot tensors,
  labels, and ragged optimizer output.
- Durable partial reads matter before resumable execution.
- Live plots and dashboards should be disposable consumers.
- Setup, procedure, parameter, registry, wiring, demod/readout, and runner
  summaries are useful context without proving physical truth.
- Code identity is separate from execution ownership.
- Analysis handoff is distinct from acquisition.
- Calibration and parameter work should first produce history, diffs, health
  gates, and working refs before mutation ownership.
- Export and handoff should preserve source identity, semantic context,
  integrity facts, and missing-context warnings.

## Evidence Anchors

| Anchor | Retained value | Current use |
| --- | --- | --- |
| Ordinary Python writer | A minimal explicit writer is a plausible adoption path for durable records. | EV-012 and durable-record pressure in [`../../evidence-register.md`](../../evidence-register.md). |
| Dataset shape variety | Regular grids, traces, complex values, IQ arrays, labels, and ragged records are needed validation cases. | EV-045 and handoff/durable-record pressure. |
| Handoff package pressure | Source identity, semantic context, integrity facts, and missing-context warnings matter more than byte copying alone. | EV-022 and selected-data handoff pressure. |
| Runnable-code context | Code, lockfiles, local environments, and copied folders are diagnostic evidence before managed execution. | EV-023 and code environment-validation pressure. |

## Current Mapping

| Lesson | Current owner |
| --- | --- |
| Measurement history is useful but too narrow as a product center. | [`../../evidence-register.md`](../../evidence-register.md) |
| Durable recording and ordinary Python substrate pressure. | [`../../evidence-register.md`](../../evidence-register.md) |
| Measurement-record adoption, including selected handoff and later traceability. | [`../../evidence-register.md`](../../evidence-register.md), [`../../../product/adoption-strategy.md`](../../../product/adoption-strategy.md) |
| Runtime, mutation, and safety boundaries. | [`../../../product/direction.md`](../../../product/direction.md) |
| Lab workflow gap checking. | [`lab-workflow-pressure-check.md`](lab-workflow-pressure-check.md) |
