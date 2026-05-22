# Measurement Context Candidate Backlog

## Status

Discovery backlog, not an ADR.

This document collects recurring candidate slices for context records attached
to or selected for measurements. It is a planning aid for validation work, not
an accepted shared schema, storage model, lifecycle model, diff engine, GUI
contract, write-back contract, or execution framework.

## Why This Exists

Several discovery routes are currently split by domain:

- parameter state;
- setup binding and station-registry context;
- experiment code context;
- declared environment context;
- recorded analysis choices;
- attachments, artifacts, and handoff context;
- selected-reference comparison context.

These are not the same domain, but they repeat the same product shape: a
measurement or calibration step can reference named, point-in-time context
records that may later be selected, compared, reviewed, exported, or checked.

The shared backlog prevents every route from carrying a separate copy of the
same candidate list. It does not mean the families share internal payloads,
version semantics, storage authority, restore behavior, or write-back rules.

## Scope

This backlog applies when a slice is about measurement context rather than
primary measurement data.

In scope:

- context record identity, provenance, family name, and declared summary;
- measurement, calibration-step, export, or handoff references to context;
- named run-start input sets;
- same-family or selected-reference comparison findings;
- reviewable context changes;
- readiness or status summaries;
- external materialization or compatibility outputs after review.

Out of scope:

- primary measurement data storage, preview, import, export, and writer
  semantics;
- final relation graph, recursive traversal, or analysis-DAG inference;
- final shared context schema or storage model;
- domain-specific payload interpretation unless a slice earns it;
- hardware write-back, dependency sync, code import, code execution, notebook
  execution, managed runners, or GUI ownership.

## Choosing A Validation Slice

Do not treat this backlog as the owner of active sequencing. The slice under
active work should be chosen in the implementation or PR plan. This backlog
only helps classify the slice once that plan chooses a concrete user pressure.

When the goal is to test whether the shared context vocabulary is useful,
**Named Run-Start Input Set** is usually the smallest cross-family validation
slice because it assembles existing selected context references, such as
parameter state, setup binding, code context or managed code version, and
measurement intent, into one run-preparation summary.

That fixture should stop at selection, labels, provenance, and missing-context
findings. It should not introduce a universal context schema, hardware control,
code import, environment sync, runnable-readiness claims, or execution.

Use the experiment-code backlog instead when the next question is about code
capture state, comparable code surfaces, workspace materialization, editable
folders, or environment readiness.

## Candidate Slice Backlog

### 1. Context Snapshot Record

Validation question: can Scopecat record a point-in-time context record with
identity, provenance, declared summary, and family-specific payload boundary?

Applies to: parameter state, setup binding, station registry context, code
context, declared environment context, analysis choices, artifacts, and
attachments.

First fixture: one family-specific context record with explicit authority,
declared summary fields, references, and opaque or family-owned payload.

Boundary: no universal context schema, final storage identity, recursive graph,
write-back, restore, import, execution, or GUI.

### 2. Measurement Or Step Context Link

Validation question: can a measurement, calibration step, export, or handoff
package reference selected context records without absorbing their domain
models?

Applies to: parameter state, setup binding, code context, environment context,
analysis choices, artifacts, attachments, and selected-reference packages.

First fixture: a measurement or step with explicit context links, family names,
roles, include state, and missing or unavailable context findings.

Boundary: no recursive relation traversal, automatic inclusion of adjacent
records, shared relation graph, restore, execution, or cause attribution.

### 3. Named Run-Start Input Set

Validation question: can Scopecat assemble selected context records as named
inputs for a run-start or run-preparation surface?

Applies to: parameter state, setup binding, station registry context, code
context, declared environment context, and measurement intent.

First fixture: one run-start input set with selected parameter state, setup
binding, code context or managed version, and declared intent.

Boundary: no universal lifecycle model, hardware control, write-back,
dependency sync, code import, runnable-readiness claim, or execution.

### 4. Context Comparison Findings

Validation question: can Scopecat report objective comparison findings between
two context records or between current and selected-reference context?

Applies to: parameter state, setup binding, station registry context, code
context, declared environment context, preview metadata, and selected-reference
review.

First fixture: one family-specific comparison with explicit authority and
findings such as same-observed, changed, missing, unverified, redacted,
unlinked, or not-compared.

Boundary: no user judgment, scientific interpretation, cause attribution,
semantic source review, setup truth, parameter invalidation, raw-data
comparison, or universal diff engine.

### 5. Reviewable Context Change

Validation question: can Scopecat represent a proposed, accepted, rejected, or
applied context change for review without taking authority to perform it?

Applies to: parameter writes, setup-binding edits, calibration writes, selected
configuration updates, and external compatibility-file updates.

First fixture: one proposed change set against a known context record, with
review status and before/after summary.

Boundary: no hardware mutation, rollback, automatic correction, durable branch
semantics, scheduler, executor, or write-back authority.

### 6. Context Readiness Or Status

Validation question: can Scopecat summarize readiness, trust, freshness,
validity, or blocked state for a context record without claiming deeper
execution authority?

Applies to: parameter trust/readiness, setup-binding validity, declared
environment inventory, running measurement context, and calibration
continuation state.

Code workspace readiness belongs to the experiment-code backlog because it
depends on managed-code, materialization, editable-folder, and environment
authority that this generic backlog does not earn.

First fixture: one context record with declared or observed readiness facts and
attention findings.

Boundary: no hardware readiness check, dependency sync, code import, setup
truth, autonomous advice, or execution unless a narrower slice earns it.

### 7. External Materialization Or Compatibility Output

Validation question: can Scopecat prepare an external representation of a
context record after review while keeping Scopecat's authority explicit?

Applies to: compatibility JSON files, setup import or validation reports,
export package context manifests, and handoff bundles.

Code workspace materialization plans belong to the experiment-code backlog
because they depend on managed-version and workspace authority.

First fixture: one reviewed context record that produces an external output
plan or materialized review artifact with source identity and skipped,
degraded, or unavailable findings.

Boundary: no importer, package writer, final external-file authority, hardware
mutation, dependency install, code import, or execution unless separately
validated.

## Domain-Specific Backlogs

Some domains need their own backlog after the common context shape is clear:

- experiment code context needs managed versions, content capture state,
  comparable code surfaces, workspace materialization, editable-folder
  observation, and environment readiness boundaries;
- parameter state needs lineage purposes, trusted versus seeded state,
  reviewable parameter writes, drift views, and optional compatibility-file
  outputs;
- setup binding needs station-registry references, setup imports, generated
  line/readout summaries, opaque project-defined payloads, and setup-truth
  deferral;
- calibration continuation needs episode context, review gates, blocked steps,
  proposed writes, targeted remeasurement intent, and possible executor
  boundaries;
- measurement records need primary-data preview, import, export, running
  inspection, writer lifecycle, and data-shape boundaries separate from
  context records.

Use this backlog to avoid duplicate slice lists. Use domain-specific backlogs
only when the validation question depends on family-specific semantics.

## Extraction Boundary

This backlog is evidence for shared vocabulary, not shared implementation.

Do not extract a shared measurement-context model until at least two validated
slices need the same behavior with matching user-visible semantics, tests, and
failure handling. Until then, each fixture may keep its own fields while using
this backlog to name the validation question it is answering.
