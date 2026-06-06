# Problem Briefs

## Status

Evidence-backed problem framing.

## Purpose

Keep user-facing failure cases close to their evidence without turning them
into requirements, validation artifacts, product scope, or prototype plans.

Problem briefs preserve observed evidence, project-owner clarification, and
historical hypotheses. They do not own active roadmap, journey/use-case
relationships, validation queues, capability maturity, or implementation
boundaries.

Use these briefs when selecting future validation questions. Use
[`../../product/target-journeys.md`](../../product/target-journeys.md) for
canonical journey/use-case ownership,
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
for validation evidence, and
[`../../engineering/implementation-register.md`](../../engineering/implementation-register.md)
for live implementation owners.

## Support Levels

| Level | Meaning |
| --- | --- |
| Direct sample evidence | Visible in static sample source, artifact metadata, or extracted research. |
| Sample plus owner clarification | The sample shows the current pattern or pressure; project-owner clarification supplies desired future meaning. |
| Owner clarification only | Explicitly clarified by the project owner, but not directly visible in the sample. |
| Historical hypothesis | A reasonable product or validation hypothesis inferred from evidence and clarification; not current scope by itself. |
| Out of scope | Too solution-shaped, under-supported, or already owned elsewhere for this brief. |

## Brief Shape

Each brief should separate:

- user-facing failure;
- observed sample evidence;
- project-owner clarification;
- historical hypotheses;
- out-of-scope items for this brief;
- possible validation questions.

Possible validation questions are prompts for future owner selection. They are
not an active task queue.

## Brief Index

| Brief | Use For |
| --- | --- |
| [`calibration-work-continuation.md`](calibration-work-continuation.md) | Sequential scans, calibration work, interruption, review gates, continuation, and thin local execution questions. |
| [`calibration-fit-validation-dataset.md`](calibration-fit-validation-dataset.md) | User-owned fit failures, suspicious-fit labeling, recovery actions, and lab-internal validation dataset curation. |
| [`parameter-state-management.md`](parameter-state-management.md) | First-class calibrated parameter state, named state lineages, purpose labels, trusted versus incomplete snapshots, reviewable diffs, run links, and write-back boundaries. |
| [`setup-binding.md`](setup-binding.md) | Sample/cooldown setup bindings between logical experiment entities and physical wiring, channels, instruments, generated line state, and measurement references. |
| [`experiment-code-recording.md`](experiment-code-recording.md) | Copied folders, entrypoint/helper ambiguity, run/step code context, environment readiness, and future code snapshot selection. |
| [`measurement-record-boundary.md`](measurement-record-boundary.md) | Measurement rows, companion artifacts, primary-data boundaries, and linked artifacts. |
| [`running-measurement-inspection.md`](running-measurement-inspection.md) | Partial recorded data, progress/readiness, stop/interruption, and monitor boundaries. |
| [`selected-run-handoff.md`](selected-run-handoff.md) | Selected-run handoff, derived analysis packages, reports, source links, and same-station access constraints. |
| [`selected-reference-comparison.md`](selected-reference-comparison.md) | Selected references, user marks, setup reality, objective comparison findings, and user-interpretation boundaries. |

## Promotion Rule

Do not promote a brief directly into product scope. First choose the smallest
validation question and attach it to the current product, engineering, or
architecture owner that will consume the evidence.
