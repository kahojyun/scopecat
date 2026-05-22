# Experiment Code Recording Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a first fixture boundary for experiment-code recording. It
does not accept final managed workspace storage, Git replacement semantics,
environment management, code execution, package/dependency closure, sync,
workflow/DAG structure, GUI design, or shared domain model extraction.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `experiment-code-selection-sample-review-2026-05-21.md`.

These notes show that current lab code recording is not a clean Git or package
problem. The sample has parallel code snapshots, dirty and nested repositories,
copied helper roots, notebook variants, checkpoint/cache/archive files,
import-time local config, private packages, LabRAD/Data Vault/MMCS/VISA-style
service assumptions, mutation-capable notebooks, and generated companions.

This plan should use that evidence to justify a smaller early boundary, not a
larger one. The first fixture should avoid reproducing the sample's noisy
directory and Git state as product output, and it should not imply that
Scopecat can already choose or load a saved code snapshot for a step.

## Validation Question

Can Scopecat record the experiment-code context associated with a run or
calibration step as an explicit point-in-time code snapshot record, using only
declared roots, entrypoints, include policy, and stripped notebooks, without
requiring users to curate the authoritative selection up front, use Git, record
every file, or accept a workflow/DAG model?

First fixture:

- `tests/fixtures/experiment_code_recording/basic_step_code_record/`

This fixture is step-centered. It records the current entrypoint and explicit
code context associated with one calibration step. Per-step saved-version
selection and system loading are deferred.

## Concept Boundary

The first boundary distinguishes:

| Concept | Meaning In This Plan |
| --- | --- |
| External code root | An existing folder or source reference that Scopecat does not yet manage. |
| Code context | The root or workspace reference, entrypoint, included files or source observations, declared context references, and policy associated with a run or calibration step. |
| Recorded code context | The audit/provenance state of a code context after Scopecat records it. It is not the active workspace that a future managed execution path may load. |
| Code snapshot record | A point-in-time code snapshot scope derived from a code context, with explicit code capture state for included items. It may later become a managed code version, but storage semantics are not accepted here. |
| Code capture state | Whether an included item is content-captured, reference-only, missing, redacted, or excluded. Capture state controls what comparison can honestly say. |
| Materialized code workspace | A future concrete folder expanded from a selected code snapshot or managed code version. Out of scope for this slice. |
| Include policy | Only explicitly included files, references, or source observations are recorded. Unrecorded folder contents are not analyzed or surfaced as warnings. |
| Entrypoint | The notebook, script, function, template, or file/cell reference associated with the run or step. |
| Notebook output stripping | Included notebooks are recorded as source without outputs. Notebook outputs and execution counts are not trusted capture payloads. |
| Declared context reference | A user-linked environment profile, setup context, generated companion, or other record reference. It is not discovered by importing code. |
| Mutation capability | Not analyzed in the first boundary. Recording does not grant execution permission. |

Internal Git state is not inspected by the first fixture. Git may become an
optional diagnostic or implementation detail later, but it should not appear in
the early-adoption record.

## First Fixture Shape

The first fixture should stay small:

- one external code root or source reference;
- one recorded notebook or script/function entrypoint;
- a small explicit include list of recorded files;
- notebook output stripping for included notebooks;
- non-recording policy for unrecorded checkpoints, caches, backups, and
  other folder contents;
- one declared environment or setup context reference;
- mutation capability marked as not analyzed;
- one calibration step referencing the recorded code context;
- one code snapshot record summary that states what Scopecat would need to
  materialize later.

## Input Boundary

Fixture input may include:

- recorded external root ID and public-safe label;
- recorded entrypoint path, kind, role, and optional symbol or cell range;
- included files and their recorded forms;
- code capture state for included files or source observations;
- notebook output-stripping policy;
- broad non-recording policy for unrecorded files;
- declared context references such as an environment profile;
- mutation capability marked as not analyzed;
- calibration-step reference to the recorded code context;
- code snapshot record fields such as record ID, snapshot scope,
  included files, recording policy, and materialization intent.

Fixture input should not include:

- raw private paths, hostnames, instrument addresses, credentials, or complete
  local service payloads;
- private full code contents in public-safe fixtures;
- internal Git state, branch names, commits, dirty summaries, or nested
  repository state;
- default record-all file listings;
- warnings derived from unrecorded files;
- notebook outputs or execution counts as trusted facts;
- imported module graphs produced by executing or importing user code;
- dependency closure through arbitrary Python;
- environment lockfiles unless they are selected/observed input;
- workflow/DAG node definitions;
- generated artifact regeneration instructions;
- hardware commands or execution requests.

## Expected Output

Expected review output should let a reviewer answer:

- what code root or source reference was recorded;
- which entrypoint was associated with the run or step;
- which files or source observations were explicitly included;
- that included notebooks were stripped to source without outputs;
- that unrecorded files were not analyzed;
- that internal Git state was not inspected;
- which declared context references are linked;
- that mutation capability was not analyzed and execution permission was not
  granted;
- which calibration step references this recorded code context;
- what point-in-time code snapshot record Scopecat may manage later.

## Capture-State Posture

Code recording can follow the same explicit-boundary posture used for
measurement attachments and artifacts: Scopecat should record what it captured,
what it only referenced, and what it cannot compare.

The first public fixture may stay synthetic and avoid private full source
payloads, but the product concept should not treat every included code item as
equally comparable. Future code comparison slices should distinguish:

- content-captured files, which can support manifest or checksum comparison
  once an integrity mechanism is validated;
- reference-only files or roots, which can support provenance and context
  comparison but should produce unverified or not-compared findings for content
  diff;
- missing or redacted code context, which should remain visible without
  implying recoverability;
- excluded or unrecorded files, which should not become noisy warnings unless
  the user records or links them.

This posture does not accept a final archive, checksum, content-addressed
store, restore, Git, or semantic source-diff contract.

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

## Slice Recommendation

Create one fixture and expected output before writing any implementation
candidate. The first goal is to validate the product posture: Scopecat can
record point-in-time code context before asking users to curate authoritative
selections or move into managed workspaces. Start with explicit include policy
and stripped notebooks; defer internal Git analysis, record-all tracking,
dependency discovery, execution, and workflow DAGs.
