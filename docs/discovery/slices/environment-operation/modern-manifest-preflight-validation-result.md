# Modern Manifest Preflight Validation Result

## Status

Implementation candidate validated.

Summary posture: `review_summary`. Fixture and expected-output artifacts are
repository-safe discovery artifacts, not portable/public/export artifacts.

Document role: historical discovery validation result. It records what this
slice earned before route-local execution/probe ownership moved into the
engineering prototype. Current implementation-boundary guidance lives in
[`prototype-readiness.md`](../../../engineering/archive/environment-operation-prototype-readiness.md);
do not update this result to mirror live API, runner, or workflow changes.

This result validates an optional Experiment Code Context review projection
slice: **Modern Manifest Preflight**.

It does not accept a general environment abstraction, environment manager,
package resolver, dependency sync contract, package-install contract, lockfile
parser, runtime-readiness check, code import, code execution, hardware-readiness
check, managed runner, shared environment schema, workflow/DAG behavior, or GUI
design.

The candidate is intentionally manager-specific: it covers a `uv` project that
declares environment intent through `pyproject.toml`. It is not a claim that all
future managers share this manifest shape. Future managers such as Pixi should
earn separate projection and operation slices before Scopecat generalizes any
manager interface.

## Fixture

Fixture:
[`../../tests/fixtures/modern_manifest_preflight/basic_pyproject_preflight/`](../../../../tests/fixtures/modern_manifest_preflight/basic_pyproject_preflight)

Implementation candidate:
[`../../implementation_candidates/modern_manifest_preflight/`](../../../../implementation_candidates/modern_manifest_preflight)

The fixture projects one approved qA chevron `pyproject.toml` manifest from
explicit prior context:

- prepared run context;
- declared `uv`/`pyproject.toml` environment reference;
- explicit preflight request and approval id;
- caller-provided workspace root plus declared manifest-relative path.

The builder reads only the approved `pyproject.toml` path under the caller root.
It parses declared project name, `requires-python`, simple dependency names,
skipped unparsed dependency entries, a synthetic `default` group from
list-shaped `[project].dependencies`, and list-shaped `[dependency-groups]`
names. Non-list `[project].dependencies` does not declare `default`. It
compares declared dependency-group expectations with groups present in the
manifest using normalized dependency-group names while preserving original
names for review display, and reports unavailable manifests, read failures,
malformed manifests, missing or malformed `requires-python`, malformed
dependency-group values, normalized dependency-group-name collisions, and
missing declared groups as review findings.
Dependency-group check rows carry the requested spelling, normalized name, and
matched manifest group spelling so review consumers do not need to compare raw
display strings.

It does not read lockfiles, resolve dependencies, run `uv`, synchronize package
state, install packages, inspect runtimes, import selected code, execute
selected code, probe hardware, or decide whether the run can start.

Raw JSON fixture input is validated into dataclass contract records before
projection. The contract validates exact top-level source shape, exact policy
shape, explicit approved operation, repository-safe managed identifiers,
non-path workspace-root label, prepared-context scope alignment, declared
environment alignment, declared `uv` manager, declared `pyproject.toml` path,
relative path syntax, exact non-operational claim shape, expected dependency
groups with normalized comparison between request and declared environment, and
policy attention boundaries. This is not a shared environment schema.

## What This Earned

The implementation candidate shows that Scopecat can project a narrow
`uv`/`pyproject.toml` review model without increasing authority to lockfile
parsing, dependency resolution, dependency sync, or package installation:

- require explicit approval for the optional `modern_manifest_preflight`
  projection;
- read exactly one declared `pyproject.toml` path under a caller-provided root;
- parse only declared manifest summary facts with stdlib `tomllib`;
- derive `default` only from list-shaped `[project].dependencies`;
- compare manifest dependency groups with declared expectations using
  normalized dependency-group names;
- report unavailable manifests, read failures, malformed manifests, missing or
  malformed `requires-python`, malformed dependency-group values, normalized
  dependency-group-name collisions, and missing-group review findings;
- keep lockfile parsing, dependency resolution, dependency sync, package
  installation, runtime probing, code import, code execution, hardware probing,
  shared environment schema, managed runners, run-blocking decisions, manager
  operation authority, and runnable-readiness claims out of scope.

## Boundary

This slice validates approved manifest review projection only.

It does not:

- read any path except the approved `pyproject.toml`;
- parse lockfiles or build dependency graphs;
- resolve, lock, sync, install, update, or remove dependencies;
- create, activate, restore, compare, or mutate virtual environments;
- inspect the active Python interpreter, installed packages, shells, hardware
  drivers, external tools, or control-PC state;
- import, load, or execute selected code;
- contact instruments, drivers, firmware utilities, services, registries, or
  hardware-control stacks;
- decide whether a run is safe, blocked, runnable, reproducible, synced, or
  scientifically valid;
- define a shared environment schema, managed runner, executor, workflow/DAG,
  or GUI workflow.

## Result

Modern manifest preflight is useful when Scopecat needs structured
environment-review or environment-comparison facts beyond file hashes and raw
text diffs. It is not required before invoking a bounded external manager
operation such as `uv sync`; for execution, `uv` remains the authority.

The result remains a review summary, not an environment operation. Manifest
facts, missing or malformed `requires-python`, malformed dependency-group
values, normalized dependency-group-name collisions, and missing declared
dependency groups remain review/comparison items. They do not become
dependency-resolution results, runtime compatibility results, hardware
readiness, runnable readiness, reproducibility, safety, or run-blocking claims.

## Follow-Up

Stop this slice at approved manifest review projection unless the next workflow
needs another manager-specific review projection or an explicitly bounded
manager operation.

Likely follow-up slices should stay separate:

- additional projection fixtures for unavailable and malformed manifests;
- approved `uv.lock` projection, if lockfile graph summaries become necessary
  for review/comparison;
- Pixi manifest projection, if Conda-capable manager support becomes a real
  workflow requirement;
- bounded manager operation intent, such as `uv sync` or a future Pixi
  operation, with command shape and working directory validated but manager
  semantics delegated to the external tool;
- manager operation result recording, capturing command, exit status, and
  summarized output without reimplementing resolution or installation;
- execution or managed-runner slices only after environment operation
  authority, hardware boundaries, and run lifecycle are separately validated.
