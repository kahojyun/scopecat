# DEC-008: Keep Experiment Code Context Separate From Runtime And Execution Ownership

## Status

Decision status: accepted.

Date: not recorded.

## Context

Experiment code in brownfield labs often lives in messy folders with notebooks,
helper packages, generated files, backups, stale Git state, unclear entrypoints,
and lab-managed environments. Scopecat needs to record useful run or step code
context before it can safely own dependency resolution, runtime probes,
execution readiness, managed deployment, or hardware-control behavior.

## Decision

Keep experiment code context separate from runtime and execution ownership.
Scopecat may record explicit code context, code snapshots, selected references,
and comparison or materialization evidence, but those records do not imply
dependency closure, execution readiness, managed deployment, remote execution,
environment mutation, or hardware-control authority.

## Scope

This decision applies to:

- Experiment Code Context support for prepared-run review, handoff,
  calibration continuation, selected-reference comparison, and reproduction;
- explicit include policies for code context recording;
- notebook-output stripping and non-recording policies for unrecorded files;
- links from measurements or calibration steps to recorded code context.

This decision does not apply to:

- future dependency resolution or runtime probing;
- managed runners, remote execution, or hardware-control authority;
- final managed workspace storage, restore, compare, or deployment contracts;
- workflow/DAG node ownership.

## Consequences

Scopecat can record and reuse useful code evidence without pretending messy
external folders are managed workspaces. Runtime, environment, execution, and
hardware boundaries must be earned by separate workflows before they become
product or architecture commitments.

## Alternatives Considered

- Option: make Git or folder structure early adoption authority. Rejected
  because legacy lab folders are often stale, copied, nested, generated, or
  otherwise unsuitable as a reliable contract.
- Option: defer all code context until managed execution exists. Rejected
  because explicit recorded code context is valuable before execution ownership
  is safe.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- users need dependency resolution, runtime probes, or execution readiness to
  become validated behavior;
- managed workspace storage, restore, comparison, or deployment becomes a
  product target;
- code context records are used as if they prove execution readiness or
  dependency closure.

## Related Evidence

- [`../product/target-journeys.md`](../product/target-journeys.md)
- [`../product/managed-experiment-code-posture.md`](../product/managed-experiment-code-posture.md)
- [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md)
- [`../discovery/problem-briefs/experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md)
