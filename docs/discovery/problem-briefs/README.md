# Problem Briefs

## Status

Evidence-backed problem framing.

## Purpose

Keep user-facing failure cases close to their evidence without turning them
into requirements, validation artifacts, or prototype plans.

A brief may combine sample-backed evidence, project-owner clarification,
derived hypotheses, and current boundaries, but it must keep those layers
separate.

Use these briefs when selecting future validation questions.

## Support Levels

| Level | Meaning |
| --- | --- |
| Direct sample evidence | Visible in static sample source, artifact metadata, or extracted research. |
| Sample plus owner clarification | The sample shows the current pattern or pressure; project-owner clarification supplies desired future meaning. |
| Owner clarification only | Explicitly clarified by the project owner, but not directly visible in the sample. |
| Derived hypothesis | A reasonable product or validation hypothesis inferred from evidence and clarification. |
| Out of scope | Too solution-shaped or under-supported for this brief. |

## Brief Shape

Each brief should separate:

- user-facing failure;
- observed sample evidence;
- project-owner clarification;
- derived hypotheses;
- out-of-scope items for this brief;
- possible validation questions.

## Brief Index

| Brief | Use For |
| --- | --- |
| [`calibration-work-review.md`](calibration-work-review.md) | Sequential scans, calibration work, interruption, review gates, continuation, and outcome questions. |
| [`parameter-mutation-history.md`](parameter-mutation-history.md) | Mutable parameter files, run-linked snapshots, drift queries, bad states, and apply/review boundaries. |
| [`code-selection-readiness.md`](code-selection-readiness.md) | Copied folders, entrypoint ambiguity, code snapshots, dependency readiness, and code-version selection. |
| [`measurement-record-attachments.md`](measurement-record-attachments.md) | Measurement rows, companion artifacts, primary-data boundaries, and attachments. |
| [`running-measurement-readability.md`](running-measurement-readability.md) | Partial recorded data, progress/readiness, stop/interruption, and live-advisory boundaries. |
| [`analysis-handoff.md`](analysis-handoff.md) | Selected-run handoff, derived analysis packages, reports, source links, and same-station access constraints. |
| [`known-good-diagnostics.md`](known-good-diagnostics.md) | Known-good references, setup reality, diagnostic support packages, and scientific comparability limits. |

## Promotion Rule

Do not promote a brief directly into product scope. First choose the smallest
validation question.
