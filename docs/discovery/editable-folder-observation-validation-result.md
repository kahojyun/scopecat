# Editable Folder Observation Validation Result

## Status

Implementation candidate validated.

This result validates the fourth Experiment Code Context backlog slice:
**Editable-Folder Observation**.

It does not accept Git checkout semantics, semantic source diff, dependency
sync, environment readiness, code import, code execution, prepared-run context,
workflow/DAG behavior, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/editable_folder_observation/basic_observation/`](../../tests/fixtures/editable_folder_observation/basic_observation/)

Implementation candidate:
[`../../implementation_candidates/editable_folder_observation/`](../../implementation_candidates/editable_folder_observation/)

The fixture starts from one selected managed code version and one editable
workspace root that was previously materialized. It includes:

- one content-available file that still matches the selected version;
- one content-available file edited after materialization;
- one content-available file missing from the editable workspace;
- one redacted file skipped without content observation;
- one unavailable file reported without requiring it to exist;
- one extra workspace note not declared by the selected version.

The candidate reads only under a caller-provided workspace root. It records
size and sha256 facts for observed regular files, treats the selected
managed-version inventory as the strong include list, treats extra files as
non-authoritative observations, skips declared workspace-internal directories
such as `.git` and `.venv` during extra-file observation, treats symlinks as
path findings without following them, and does not mutate the workspace.

## What This Earned

The implementation candidate shows that read-only editable-folder observation
can:

- preserve selected managed-version identity and storage authority;
- compare expected content-available files by size and sha256 digest;
- report same-observed, changed-observed, missing-expected, redacted,
  unavailable, and extra observed findings;
- include observed content facts for regular files without importing or
  executing code;
- keep extra files outside the selected code-surface authority until a later
  explicit promotion or recording step;
- skip declared workspace-internal directories without reporting their
  contents;
- avoid reading redacted or unavailable managed-version paths;
- treat symlink targets as observable findings without following them;
- return deterministic request, file-observation, and attention summaries.

## Boundary

This slice validates read-only observation of a selected editable workspace
root only.

It does not:

- infer semantic source diffs, user intent, generated-artifact dependencies, or
  change causes;
- inspect Git state, branches, commits, dirty status, or merge state;
- treat extra workspace files as included code context;
- restore dependencies, lockfiles, interpreters, notebooks, or environments;
- import, load, or execute code;
- create, edit, overwrite, delete, repair, or rematerialize workspace files;
- decide whether the workspace is ready for a prepared run;
- define final managed-workspace storage, collaboration, GUI, or run-preparation
  behavior.

## Result

Editable-folder observation is useful after workspace materialization when the
workflow needs to review drift from the selected managed code version before
manual editing or run preparation. The result keeps the selected managed
version's include list authoritative for code-surface comparison, while using
ignore guardrails to avoid noisy or sensitive workspace internals. Observation
remains separate from semantic diff, Git diagnostics, environment readiness,
execution, and the separate prepared-run context assembly slice.

## Follow-Up

Stop this slice at read-only observation unless the next workflow needs another
authority case.

Likely follow-up slices should stay separate:

- reference-based rerun preparation after a selected reference measurement
  needs to seed manual run context;
- declared environment inventory, still without dependency sync or runnable
  readiness claims;
- semantic source diff or Git diagnostics only after a narrower workflow
  requires those stronger claims.
