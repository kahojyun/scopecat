# Problem Briefs

## Status

Evidence-backed problem framing.

## Purpose

Keep user-facing failure cases close to their evidence without turning them
into requirements, validation artifacts, or prototype plans.

A brief may combine sample-backed evidence, project-owner clarification,
derived hypotheses, and current boundaries, but it must keep those layers
separate.

Use these briefs when selecting future validation questions. Create a
validation charter only after a brief raises a concrete question that cannot be
resolved by evidence review alone.

## Support Levels

| Level | Meaning |
| --- | --- |
| Direct sample evidence | Visible in static sample source, artifact metadata, or extracted research. |
| Sample plus owner clarification | The sample shows the current pattern or pressure; project-owner clarification supplies desired future meaning. |
| Owner clarification only | Explicitly clarified by the project owner, but not directly visible in the sample. |
| Derived hypothesis | A reasonable product or validation hypothesis inferred from evidence and clarification. |
| Current boundary | Too solution-shaped or under-supported for current product scope. |

## Brief Index

| Brief | Use For |
| --- | --- |
| [`batch-failure-review.md`](batch-failure-review.md) | Sequential scans, calibration batches, interruption, failure/review, and minimal-executor questions. |
| [`parameter-mutation-history.md`](parameter-mutation-history.md) | Mutable parameter files, run-linked snapshots, drift queries, bad states, and apply/review boundaries. |
| [`copied-code-provenance.md`](copied-code-provenance.md) | Copied folders, entrypoint ambiguity, code snapshots, dependency readiness, and code-version selection. |
| [`measurement-artifact-ownership.md`](measurement-artifact-ownership.md) | Measurement rows, companion artifacts, primary-data ownership, and attachments. |
| [`running-run-partial-records.md`](running-run-partial-records.md) | Partial recorded data, progress/readiness, stop/interruption, and live-advisory boundaries. |
| [`analysis-handoff-lineage.md`](analysis-handoff-lineage.md) | Selected-run handoff, derived analysis packages, reports, source links, and same-station access constraints. |
| [`diagnostics-comparability.md`](diagnostics-comparability.md) | Known-good references, setup reality, diagnostic support packages, and scientific comparability limits. |

## Promotion Rule

Do not promote a brief directly into product scope. First choose the smallest
validation question, then decide whether it needs user review, a reference
case, an interactive prototype, or an ADR.
