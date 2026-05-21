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

This plan should use that evidence for realism without making the sample's
directory structure the desired product model.

## Validation Question

Can Scopecat represent a messy external experiment-code folder as explicit
selected code context and a candidate captured version, without requiring users
to use Git or forcing a workflow/DAG model?

First fixture:

- `tests/fixtures/experiment_code_selection/messy_external_capture/`

## Concept Boundary

The first boundary distinguishes:

| Concept | Meaning In This Plan |
| --- | --- |
| External code root | A user-selected existing folder that Scopecat does not yet manage. |
| Selected code context | The explicit root, entrypoint, helper scope, generated companions, exclusions, environment hints, and warnings the user means to carry forward. |
| Captured version candidate | A proposed Scopecat-managed point-in-time version of the selected context. It may later become a managed version, but storage semantics are not accepted here. |
| Observed version state | Evidence such as Git commit, dirty/untracked/deleted state, nested repositories, checksums, mtimes, or snapshot time. Git is evidence, not authority. |
| Entrypoint | The notebook, script, function, template, or file/cell selection a user intends to run, inspect, restore, or hand off. |
| Helper scope | Included helper roots and files needed by the selected entrypoint, as declared or selected. It is not deep static dependency closure. |
| Generated companion | Observed or selected code-derived artifacts such as circuit JSON, chip/line info, registry views, mapping files, or derived arrays. They are not silently regenerated. |
| Environment profile hint | Recorded interpreter, package, service, local path, and hardware-stack assumptions. It is not full environment management. |
| Mutation capability | Whether selected code appears analysis-only, parameter-mutating, hardware-active, or unknown. This is an attention state, not execution permission. |

The fixture may use Git-like words such as commit or dirty state when observed,
but the product concept under validation is a Scopecat selected-code context
and captured-version candidate.

## First Fixture Shape

The first fixture should stay small:

- one external code root;
- one selected notebook or script/function entrypoint;
- two included helper roots;
- one generated companion linked as observed/selected;
- one excluded checkpoint/cache path;
- one backup or dated variant shown as ambiguity, not automatically selected;
- one observed Git state that is stale or dirty;
- one nested repository or helper-root version warning;
- one environment profile hint with redacted local-service assumptions;
- one mutation-capability classification;
- one measurement or calibration step referencing the selected code context;
- one captured-version candidate summary that states what Scopecat would need
  to materialize later.

## Input Boundary

Fixture input may include:

- selected external root ID and public-safe label;
- selected entrypoint path, kind, role, and optional symbol or cell range;
- included helper roots and explicit include/exclude/classify rules;
- observed version state, including Git evidence when present;
- generated companions with source relation and generation status;
- environment hints such as interpreter name, package assumptions, services,
  local path requirements, and hardware-stack assumptions;
- mutation capability and static attention items;
- measurement or calibration-step reference to the selected code context;
- captured-version candidate fields such as candidate ID, capture scope,
  observed files, excluded files, warnings, and materialization intent.

Fixture input should not include:

- raw private paths, hostnames, instrument addresses, credentials, or complete
  local service payloads;
- full code contents;
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
- which helper scope is included and which files are excluded or classified;
- what Git or file-state evidence was observed, and why Git is not treated as
  product authority;
- which backup/checkpoint/nested-repository conditions create ambiguity;
- which generated companions are linked without regeneration;
- which environment and local-service assumptions affect portability;
- whether the code appears analysis-only, parameter-mutating, hardware-active,
  or unknown;
- which measurement or calibration step references this selected code context;
- what would be captured as a Scopecat-managed version candidate.

## Out Of Scope

This plan does not earn:

- final managed workspace storage;
- final file snapshot or checksum contract;
- Git replacement implementation;
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
opinionated about selected-code records and captured-version candidates without
requiring users to understand Git or prematurely structuring their code as a
workflow DAG.
