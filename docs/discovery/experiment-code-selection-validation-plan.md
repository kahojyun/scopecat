# Experiment Code Selection Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a first fixture boundary for experiment-code selection. It
does not accept final managed workspace storage, Git replacement semantics,
environment management, code execution, package/dependency closure, sync,
workflow/DAG structure, GUI design, or shared domain model extraction.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `experiment-code-selection-sample-review-2026-05-21.md`.

These notes show that current lab code selection is not a clean Git or package
problem. The sample has parallel code snapshots, dirty and nested repositories,
copied helper roots, notebook variants, checkpoint/cache/archive files,
import-time local config, private packages, LabRAD/Data Vault/MMCS/VISA-style
service assumptions, mutation-capable notebooks, and generated companions.

This plan should use that evidence to justify a smaller early boundary, not a
larger one. The first fixture should avoid reproducing the sample's noisy
directory and Git state as product output.

## Validation Question

Can Scopecat represent a messy external experiment-code folder as an explicit
point-in-time code version/snapshot candidate, defined by selected code
context, using only a minimal user whitelist and stripped notebooks, without
requiring users to use Git, recording every file, or forcing a workflow/DAG
model?

First fixture:

- `tests/fixtures/experiment_code_selection/messy_external_capture/`

## Concept Boundary

The first boundary distinguishes:

| Concept | Meaning In This Plan |
| --- | --- |
| External code root | A user-selected existing folder that Scopecat does not yet manage. |
| Selected code context | The explicit root, entrypoint, whitelisted files, declared context references, and capture policy that define the scope of a code version/snapshot. Selection is the action that chooses the scope, not the durable concept by itself. |
| Captured version candidate | A proposed point-in-time code snapshot for future Scopecat-managed versions. It may later become a managed version, but storage semantics are not accepted here. |
| Whitelist capture | Only user-selected files or references are recorded. Unselected folder contents are not analyzed or surfaced as warnings. |
| Entrypoint | The notebook, script, function, template, or file/cell selection a user intends to run, inspect, restore, or hand off. |
| Notebook output stripping | Whitelisted notebooks are recorded as source without outputs. Notebook outputs and execution counts are not trusted capture payloads. |
| Declared context reference | A user-linked environment profile, setup context, generated companion, or other record reference. It is not discovered by importing code. |
| Mutation capability | Not analyzed in the first boundary. Selection does not grant execution permission. |

Internal Git state is not inspected by the first fixture. Git may become an
optional diagnostic or implementation detail later, but it should not appear in
the early-adoption record.

## First Fixture Shape

The first fixture should stay small:

- one external code root;
- one selected notebook or script/function entrypoint;
- a small whitelist of selected files;
- notebook output stripping for whitelisted notebooks;
- non-recording policy for unwhitelisted checkpoints, caches, backups, and
  other folder contents;
- one declared environment or setup context reference;
- mutation capability marked as not analyzed;
- one measurement or calibration step referencing the selected code context;
- one captured code-version candidate summary that states what Scopecat would
  need to materialize later.

## Input Boundary

Fixture input may include:

- selected external root ID and public-safe label;
- selected entrypoint path, kind, role, and optional symbol or cell range;
- whitelisted files and their recorded forms;
- notebook output-stripping policy;
- broad non-recording policy for unwhitelisted files;
- declared context references such as an environment profile;
- mutation capability marked as not analyzed;
- measurement or calibration-step reference to the selected code context;
- captured code-version candidate fields such as candidate ID, capture scope,
  whitelisted files, recording policy, and materialization intent.

Fixture input should not include:

- raw private paths, hostnames, instrument addresses, credentials, or complete
  local service payloads;
- full code contents;
- internal Git state, branch names, commits, dirty summaries, or nested
  repository state;
- default record-all file listings;
- warnings derived from unselected files;
- notebook outputs or execution counts as trusted facts;
- imported module graphs produced by executing or importing user code;
- dependency closure through arbitrary Python;
- environment lockfiles unless they are selected/observed input;
- workflow/DAG node definitions;
- generated artifact regeneration instructions;
- hardware commands or execution requests.

## Expected Output

Expected review output should let a reviewer answer:

- what code root the user selected;
- which entrypoint the user intends to use;
- which files are whitelisted;
- that whitelisted notebooks were stripped to source without outputs;
- that unwhitelisted files were not recorded or analyzed;
- that internal Git state was not inspected;
- which declared context references are linked;
- that mutation capability was not analyzed and execution permission was not
  granted;
- which measurement or calibration step references this selected code context;
- what point-in-time code snapshot would be captured as a Scopecat-managed
  version candidate.

## Out Of Scope

This plan does not earn:

- final managed workspace storage;
- final file snapshot or checksum contract;
- Git replacement implementation;
- internal Git analysis;
- default record-all file tracking;
- branch, merge, conflict, or sync semantics;
- package management, dependency closure, or virtual environment ownership;
- code execution, notebook execution, static import execution, or hardware
  readiness execution;
- workflow/DAG nodes or component-level versioning;
- generated artifact regeneration or build pipelines;
- GUI design;
- shared domain model extraction.

## Current Recommendation

Create one fixture and expected output before writing any implementation
candidate. The first goal is to validate the product posture: Scopecat can be
opinionated about point-in-time code version records and captured-version
candidates while keeping early adoption minimal. Start with whitelist capture and stripped
notebooks; defer internal Git analysis, record-all tracking, dependency
discovery, execution, and workflow DAGs.
