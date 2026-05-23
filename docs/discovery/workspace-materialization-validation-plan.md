# Workspace Materialization Validation Plan

## Status

Validation plan, not an ADR.

This plan targets the third Experiment Code Context backlog slice:
**Workspace Materialization**.

It does not accept final managed workspace storage, Git checkout semantics,
merge behavior, dependency sync, environment restoration, code import, code
execution, workflow/DAG behavior, or GUI design.

## Validation Question

Can Scopecat create an editable workspace from an approved selected managed
code version while keeping file writes explicit, bounded, and reviewable?

## Inputs

- [`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md)
- [`managed-code-version-validation-result.md`](managed-code-version-validation-result.md)
- [`workspace-materialization-intent-validation-result.md`](workspace-materialization-intent-validation-result.md)
- `tests/fixtures/workspace_materialization/basic_workspace/`

## Fixture Boundary

The first fixture should start from one selected managed code version and one
approved materialization request. It should include:

- one content-available file that can be written to a new target path;
- one content-available file whose target path already exists and must not be
  overwritten;
- one redacted file that must not be materialized;
- one unavailable file that cannot be restored.

The fixture should keep managed content small, explicit, public-safe, and
stored under the fixture. Required fields must appear in the fixture input,
including approval state, destination policy, materialization paths, content
references, content size, sha256 digest hints, and any preexisting target paths
the test creates before materialization.

## Expected Candidate Behavior

A narrow implementation candidate may:

- accept a caller-provided managed-content root and workspace root;
- validate the approved selected managed-version request;
- validate all declared content size and sha256 digest facts before writing;
- create target directories under the caller-provided workspace root;
- write only content-available files whose target path does not already exist,
  using exclusive-create writes;
- report existing targets without overwriting them;
- report redacted and unavailable files without creating placeholders;
- return a structured summary of written, skipped, redacted, and unavailable
  paths.

## Out Of Scope

This slice must not:

- write outside the caller-provided workspace root;
- overwrite, merge, rename, or delete destination entries;
- follow symlink targets for materialization paths;
- treat the workspace as a Git checkout, branch, merge target, or sync target;
- restore dependencies, lockfiles, interpreters, notebooks, or environments;
- import, load, or execute code;
- infer missing files from the filesystem or scan the full destination tree;
- define final managed-workspace storage, GUI, or collaboration behavior.

## Validation Checks

Tests should confirm:

- the expected available file is written and the existing target is unchanged;
- redacted and unavailable files are not created;
- declared digest and size mismatches fail before any file is written;
- symlink targets are reported as existing targets rather than followed;
- positive claims about execution, dependency sync, or broader authority are
  rejected;
- unapproved requests are rejected;
- relative path boundaries are enforced;
- the returned summary matches the fixture expected output.

## Pass Criteria

The slice passes when the candidate can materialize the fixture workspace in a
temporary caller-provided root, produce deterministic expected output, and keep
all stronger workspace, environment, Git, import, execution, and GUI claims
out of the contract.
