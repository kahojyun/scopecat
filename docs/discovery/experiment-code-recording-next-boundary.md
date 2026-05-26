# Experiment Code Recording Next Boundary

## Status

Discovery boundary note, not an ADR.

This note closes the current experiment-code recording slice by separating what
the first adoption path has earned, how users may adopt later managed-code
workflows, and which validation slices should earn stronger claims next.

## Earned Now

The current slice earns a recording-first path for experiment code contexts
and code snapshot records:

- users can record the external code root, entrypoint, explicitly included
  files, and declared context references associated with a measurement or
  calibration step;
- Scopecat can record that context without inspecting internal Git state,
  scanning unrecorded files, or analyzing the whole legacy codebase;
- included notebooks can be recorded as source without outputs;
- unrecorded files, backups, caches, checkpoints, generated files, and copied
  helper folders remain outside the record unless the user records or links
  them;
- the recorded code context can be referenced by measurement export,
  selected-reference comparison, setup-binding review, and calibration
  continuation;
- a code snapshot record can name the future Scopecat-managed snapshot scope
  without accepting storage, restore, merge, sync, or execution contracts.

`Recorded` names the audit state of a code context. It should not become the
name for a future active workspace that Scopecat materializes. A later managed
path should distinguish the selected snapshot/version from the concrete
materialized code workspace.

Code records should also distinguish capture state. Some included items may be
content-captured, while others may be reference-only, missing, redacted, or
excluded. That is acceptable for early adoption as long as comparison and
restore surfaces show the limitation instead of pretending all included items
are equally recoverable or comparable.

This is enough to cover the first adoption value: record the code most directly
tied to experiment workflow and intent while avoiding legacy-codebase analysis.
Selection can later choose, promote, or restore one of those records; it should
not be the first adoption gate.

The transition into managed code should be explicit rather than pretending that
recorded history and managed history are one continuous version line:

```text
recorded code context
  -> code snapshot record with capture-state facts
  -> promoted managed code version
  -> materialized editable workspace
```

Only captured or recaptured content should become a strong managed-version
inventory. Reference-only prior records can remain useful evidence, but they
should carry unverified or not-compared findings when users ask for content
comparison.

## Not Earned Yet

The current slice does not earn:

- final managed workspace storage;
- a file snapshot, checksum, archive, or content-addressed store contract;
- a Git replacement implementation;
- internal Git diagnostics as product output;
- default record-all file tracking;
- branch, merge, conflict, push, pull, sync, or collaboration semantics;
- package or environment ownership;
- loading a selected code snapshot or managed code version for execution;
- `uv sync` or lockfile-driven environment restoration;
- notebook execution, code import, dependency discovery, or hardware readiness
  checks;
- workflow/DAG nodes, component-level code versions, or compatibility
  contracts;
- generated artifact regeneration or build-pipeline validation;
- GUI design.

These remain plausible future capabilities. They are not required for the
first code snapshot record to be useful.

## Code-Context Adoption Boundary

The route-level adoption path is owned by
[`adoption-routes.md`](adoption-routes.md). This note only keeps the
experiment-code boundary implication: recording-first value should remain
useful before a lab adopts managed code versions, workspace materialization,
editable-folder observation, prepared run context, rerun preparation, or
environment help.

Later managed-workspace steps are optional workflow branches, not a single
linear product journey or prerequisite for useful run/step code recording.

## Validation Slice Order

Validation should follow authority boundaries more strictly than user adoption:

1. Validate a comparable code surface over explicit code facts before claiming
   a general diff, editable-folder readiness, or runnable context.
2. Validate workspace materialization intent before creating editable
   workspaces.
3. Validate workspace materialization before treating a current editable folder
   as a managed-version readiness target.
4. Validate editable-folder observation against a selected managed version or
   materialized workspace before preparing a run context.
5. Validate prepared run context from selected managed code version, editable
   workspace observation, selected parameter state, setup binding, and
   measurement intent.
6. Validate declared environment inventory before environment readiness
   planning, and keep any active dependency sync for a later modern-manifest
   operation slice; legacy/lab-managed environment facts stay record-only.
7. Validate reference-based rerun preparation as a convenience workflow over
   prepared run context, not as a separate reproducibility claim.
8. Validate environment readiness planning from declared environment context
   before attempting dependency resolution, dependency sync, package
   installation, runtime probes, hardware checks, or managed runners.
9. Validate environment comparison findings before treating selected-reference
   and current declared environment differences as dependency resolution,
   dependency sync, package installation, runtime compatibility checks, hardware
   readiness, or runnable readiness.
10. Validate environment file observation before treating declared modern
    manifests or lockfiles as dependency-resolution, sync, runtime,
    hardware-readiness, or runnable-readiness inputs.
11. Validate environment review bundle composition before turning comparison,
    file observation, or readiness-plan findings into approved dependency
    resolution, dependency sync, package installation, runtime checks, shared
    environment schema, managed runners, run-blocking decisions, or
    runnable-readiness claims.
12. Validate approved modern manifest preflight before treating a declared
    `pyproject.toml` as dependency resolution, dependency sync, package
    installation, runtime compatibility, run-blocking, or runnable-readiness
    evidence.

## Validation Slice Backlog

This backlog names experiment-code validation questions and links to result
owners where first results already exist. Individual validation result docs own
durable result details. Each slice must still keep its own authority and
fixture boundary when extended.

### 1. Comparable Code Surface

Validation question: can Scopecat compare explicit code fact sets without
pretending every included item is content-comparable?

User pressure: users need to compare recorded or managed code contexts and
understand findings such as same-observed, changed, missing, unverified,
redacted, or not-compared. Capture states such as reference-only and excluded
should explain why a content comparison is unavailable; they are not comparison
findings by themselves.

Result owner:
[`comparable-code-surface-validation-result.md`](comparable-code-surface-validation-result.md)

Boundary: no universal diff engine, semantic source diff, Git analysis,
environment readiness, import, or execution.

Later fixture cases: managed-version inventory comparison, capture-state edge
cases that need their own fixture, additional editable-folder observation
cases, and materialized-directory comparison.

### 2. Workspace Materialization Intent

Validation question: can Scopecat plan where a selected managed version would
be materialized before writing files?

User pressure: users need preview, naming, collision, overwrite, and provenance
clarity before restoring or editing code.

First fixture: a selected managed code version plus candidate destination
policy, producing a materialization plan with destination paths, collision
findings, provenance labels, and skipped, redacted, or unavailable file
findings.

Result owner:
[`workspace-materialization-intent-validation-result.md`](workspace-materialization-intent-validation-result.md)

Boundary: no file writes, Git UI, merge model, dependency install, import, or
execution.

### 3. Workspace Materialization

Validation question: can Scopecat create an editable workspace from a selected
managed version?

User pressure: users need to restore a code snapshot on the same or another
machine and move from external-folder references to Scopecat-owned code
storage.

First fixture: a selected managed code version and approved materialization
target, producing an editable workspace with provenance back to the managed
version and explicit skipped, redacted, or unavailable file findings.

Result owner:
[`workspace-materialization-validation-result.md`](workspace-materialization-validation-result.md)

Boundary: no Git UI, merge model, dependency install, import, environment sync,
or execution.

### 4. Editable-Folder Observation

Validation question: can Scopecat compare an observed editable folder against a
selected managed version or materialized workspace?

User pressure: users need to know whether the folder they are about to edit or
run still matches the selected managed code surface.

First fixture: an observed editable folder and selected managed version,
producing comparable file findings over known observed facts.

Result owner:
[`editable-folder-observation-validation-result.md`](editable-folder-observation-validation-result.md)

Boundary: no Git diff, semantic source diff, dependency readiness, import,
environment readiness, or execution.

### 5. Prepared Run Context

Validation question: can Scopecat assemble selected managed code version,
editable workspace observation, parameter state, setup binding, and
measurement intent as a named run-start context?

User pressure: users want a Labber-like run-preparation experience while still
running existing lab code outside Scopecat.

First fixture: selected managed code version, declared editable-workspace
observation, selected parameter state, setup binding, and measurement intent,
producing a run-preparation summary.

Result owner:
[`prepared-run-context-validation-result.md`](prepared-run-context-validation-result.md)

Boundary: no execution, hardware control, environment sync, or claim that the
selected context is runnable.

### 6. Declared Environment Inventory

Validation question: can Scopecat record declared environment facts next to the
selected code context?

User pressure: users need environment files, lockfiles, interpreter hints, and
package-manager hints to be visible with code history before any sync is
attempted.

First fixture: a managed code version plus user-declared environment file,
lockfile, interpreter, package, and external-tool references, producing
declared, unavailable, unverified, redacted, unsupported, unpinned, or unknown
findings.

Result owner:
[`declared-environment-inventory-validation-result.md`](declared-environment-inventory-validation-result.md)

Boundary: no sync, import, dependency resolution, hardware readiness, runnable
readiness, or execution.

### 7. Reference-Based Rerun Preparation

Validation question: can Scopecat start from a selected reference measurement
and prepare the matching manual rerun context?

User pressure: users want a prior measurement to seed code, parameter, setup,
and intent selection for a manual rerun.

First fixture: a selected reference measurement with linked code context,
parameter state, and setup binding, producing a proposed prepared run context.

Result owner:
[`reference-based-rerun-preparation-validation-result.md`](reference-based-rerun-preparation-validation-result.md)

Boundary: no reproducibility guarantee, cause attribution, execution, hardware
control, or automatic correction of drift.

### 8. Environment Readiness Planning

Validation question: can Scopecat plan what environment checks would be needed
for a selected declared modern Python environment context?

User pressure: restored code alone may be insufficient when users need to know
what would need review before the declared environment can be trusted.

First fixture: a declared modern `uv`/`pyproject.toml` environment record plus
explicit check intentions, producing a readiness plan that says what would be
checked.

Result owner:
[`environment-readiness-validation-result.md`](environment-readiness-validation-result.md)

Boundary: no dependency resolution, dependency sync, package installation,
runtime probes, hardware-active import, notebook execution, managed runner,
runnable-readiness claim, or claim that the experiment result is reproducible.

### 9. Environment Comparison Findings

Validation question: can Scopecat compare two declared environment contexts
without resolving, syncing, probing, importing, executing, or claiming runnable
readiness?

User pressure: users reviewing a selected-reference rerun need to see whether
the declared environment context differs from the current proposed run context
before any environment operation is approved.

First fixture: a selected-reference declared environment context and current
declared environment context, producing same-declared, changed, missing,
unverified, and unsupported findings over explicit environment facts.

Result owner:
[`environment-comparison-validation-result.md`](environment-comparison-validation-result.md)

Boundary: no file reads, dependency resolution, dependency sync, package
installation, runtime probes, hardware probes, code import, code execution,
shared environment schema, or runnable-readiness claim.

### 10. Environment File Observation

Validation question: can Scopecat observe explicitly declared environment files
under a caller-provided workspace root without discovering workspaces,
resolving dependencies, syncing packages, probing runtimes, importing code,
executing code, or claiming runnable readiness?

User pressure: users reviewing a current manual run context need to know
whether the declared modern environment files are present and match declared
file facts before any environment operation is approved.

First fixture: a current declared environment context with explicit
`pyproject.toml` and `uv.lock` relative paths, producing availability, sha256,
byte-size, mismatch, malformed-manifest review findings, and narrow
`pyproject.toml` declared manifest summary facts.

Result owner:
[`environment-file-observation-validation-result.md`](environment-file-observation-validation-result.md)

Boundary: no workspace discovery, lockfile dependency-graph parsing,
dependency resolution, dependency sync, package installation, runtime probes,
hardware probes, code import, code execution, shared environment schema, or
runnable-readiness claim.

### 11. Environment Review Bundle

Validation question: can Scopecat compose prepared/rerun context, declared
environment comparison, file observation, and readiness-plan summaries into one
review bundle without performing fresh environment operations?

User pressure: users reviewing a selected-reference manual rerun need one
place to see declared environment differences, observed file status, and
planned check findings before approving any later environment operation.

First fixture: a current manual rerun context with selected-reference and
current declared environment records, a declared comparison summary, a file
observation summary, and a readiness-plan summary, producing one environment
review bundle.

Result owner:
[`environment-review-bundle-validation-result.md`](environment-review-bundle-validation-result.md)

Boundary: no fresh file reads, dependency resolution, dependency sync, package
installation, runtime probes, hardware probes, code import, code execution,
shared environment schema, managed runner, run-blocking decision, or
runnable-readiness claim.

### 12. Modern Manifest Preflight

Validation question: can Scopecat read one explicitly approved modern
`pyproject.toml` manifest and summarize declared manifest facts without
performing lockfile parsing, dependency resolution, dependency sync, or package
installation?

User pressure: users approving a later environment operation need to know
whether the current manifest is readable and whether declared dependency-group
expectations appear in the manifest before any dependency resolution or sync is
approved.

First fixture: an approved qA chevron preflight request with prepared run
context, declared current `uv` environment context, caller-provided workspace
root, and declared `pyproject.toml` path, producing parsed manifest summary
facts plus review findings for missing or malformed `requires-python`,
malformed dependency-group values, and missing declared dependency groups.

Result owner:
[`modern-manifest-preflight-validation-result.md`](modern-manifest-preflight-validation-result.md)

Boundary: one approved `pyproject.toml` read only; no lockfile parsing,
dependency resolution, dependency sync, package installation, runtime probes,
hardware probes, code import, code execution, shared environment schema,
managed runner, run-blocking decision, or runnable-readiness claim.

All slices should keep code execution separate from code record integrity and
environment planning until an explicit execution slice earns that authority.
