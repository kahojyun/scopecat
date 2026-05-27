# UV Sync Intent Validation Result

## Status

Implementation candidate validated.

Summary posture: `review_summary`. Fixture and expected-output artifacts are
repository-safe discovery artifacts, not portable/public/export artifacts.

This result validates a narrow Experiment Code Context operation-intent slice:
**UV Sync Intent**.

It does not accept a general environment-manager abstraction, Pixi/Conda
manager interface, manifest parser, lockfile parser, dependency resolver,
dependency-sync executor, package-install contract, runtime-readiness check,
code import, code execution, hardware-readiness check, managed runner,
workflow/DAG behavior, run-blocking decision, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/uv_sync_intent/basic_uv_sync_intent/`](../../tests/fixtures/uv_sync_intent/basic_uv_sync_intent/)

Implementation candidate:
[`../../implementation_candidates/uv_sync_intent/`](../../implementation_candidates/uv_sync_intent/)

The fixture projects one approved qA chevron `uv sync` intent from explicit
prior context:

- prepared run context;
- declared `uv`/`pyproject.toml` environment reference;
- explicit sync-intent request and approval id;
- declared workspace-root label and relative working directory.

The builder does not receive or open a workspace root. It validates only
declared syntax and continuity, then constructs bounded argv:

```text
uv sync --locked --no-default-groups --group analysis
```

The first operation policy is deliberately narrow: include project
dependencies, exclude uv default dependency groups, add only selected
declared uv dependency groups, and construct argv with `--locked`. If a later
executor runs the command, uv decides whether the lockfile would remain
unchanged and reports failure.

Raw JSON fixture input is validated into dataclass contract records before
projection. The contract validates exact top-level source shape, exact policy
shape, explicit approved operation, repository-safe managed identifiers,
non-path workspace-root label, declared relative working directory, prepared
context scope alignment, declared environment alignment, declared `uv` manager,
declared `pyproject.toml` and lockfile paths, dependency groups with normalized
comparison between request and declared environment, bounded sync mode, bounded
lock policy, bounded command policy, clean declared-environment record status,
and policy attention boundaries. This is not a shared environment schema.

For this first `--locked` command policy, the declared lockfile path must name
`uv.lock` beside the declared `pyproject.toml`. The candidate still does not
read or parse that lockfile.

When request and declared-environment group names match only after
normalization, the command uses the declared-environment spelling because that
is the environment reference being handed to the external manager.

## What This Earned

The implementation candidate shows that Scopecat can prepare a reviewable
external manager operation without taking over manager semantics:

- require explicit approval for `uv_sync_intent`;
- validate the requested manager, working directory, prepared context, declared
  environment, and dependency-group continuity;
- construct exact argv from structured fields rather than accepting arbitrary
  caller flags;
- keep `--locked` and `--no-default-groups` as the first conservative command
  policy;
- keep manifest reads, lockfile reads, dependency resolution, process
  execution, dependency sync, package installation, runtime probing, code
  import, code execution, hardware probing, shared environment schema, managed
  runners, run-blocking decisions, and runnable-readiness claims out of scope.

## Boundary

This slice validates approved command intent only.

It does not:

- inspect whether the workspace, working directory, manifest, lockfile,
  interpreter, virtualenv, packages, or tools exist;
- read `pyproject.toml` or `uv.lock`;
- parse manifests or lockfiles;
- resolve, lock, sync, install, update, or remove dependencies;
- spawn subprocesses or run `uv`;
- create, activate, restore, compare, or mutate virtual environments;
- inspect the active Python interpreter, shells, hardware drivers, external
  tools, or control-PC state;
- import, load, or execute selected code;
- contact instruments, drivers, firmware utilities, services, registries, or
  hardware-control stacks;
- decide whether a run is safe, blocked, runnable, reproducible, synced, or
  scientifically valid;
- define a shared environment schema, manager interface, managed runner,
  executor, workflow/DAG, or GUI workflow.

## Result

UV sync intent is useful when Scopecat has enough declared environment context
to present a bounded external command for post-approval review or later
executor handoff.
Execution and semantics remain outside the slice: `uv` remains the authority
for lock validation, resolution, synchronization, and package installation if
the command is actually run.

The result stays separate from modern manifest preflight. Manifest preflight is
optional review projection; uv sync intent is operation-intent projection.
Neither one is a prerequisite for the other, and neither defines a general
manager abstraction.

## Follow-Up

Stop this slice at bounded `uv sync` command intent unless the next workflow
needs one of these separate capabilities:

- approved `uv sync` execution result recording, capturing argv, cwd, exit
  status, and summarized output without reimplementing uv semantics;
- additional uv command policies, each with explicit argv construction and
  tests rather than arbitrary flags;
- Pixi operation intent as a separate manager-specific slice before any shared
  abstraction is extracted;
- runtime or hardware readiness checks only after operation-result and
  execution boundaries are separately validated.
