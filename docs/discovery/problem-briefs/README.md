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
| [`calibration-work-continuation.md`](calibration-work-continuation.md) | Sequential scans, calibration work, interruption, review gates, continuation, and thin local execution questions. |
| [`parameter-state-history.md`](parameter-state-history.md) | First-class calibrated parameter state, named state lineages, purpose labels, trusted versus incomplete snapshots, reviewable diffs, run links, and write-back boundaries. |
| [`experiment-code-selection.md`](experiment-code-selection.md) | Copied folders, entrypoint ambiguity, code snapshots, environment validation, and code-version selection. |
| [`measurement-record-boundary.md`](measurement-record-boundary.md) | Measurement rows, companion artifacts, primary-data boundaries, and linked artifacts. |
| [`running-measurement-inspection.md`](running-measurement-inspection.md) | Partial recorded data, progress/readiness, stop/interruption, and monitor boundaries. |
| [`selected-run-handoff.md`](selected-run-handoff.md) | Selected-run handoff, derived analysis packages, reports, source links, and same-station access constraints. |
| [`selected-reference-comparison.md`](selected-reference-comparison.md) | Selected references, known-good as a narrower subtype, setup reality, comparison findings, and scientific comparability limits. |

## Promotion Rule

Do not promote a brief directly into product scope. First choose the smallest
validation question.
