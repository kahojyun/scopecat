# Modern Manifest Preflight Validation Result

## Status

Implementation candidate validated.

Summary posture: `review_summary`. Fixture and expected-output artifacts are
repository-safe discovery artifacts, not portable/public/export artifacts.

This result validates a follow-up Experiment Code Context operation-shaped
slice: **Modern Manifest Preflight**.

It does not accept an environment manager, package resolver, dependency sync
contract, package-install contract, lockfile parser, runtime-readiness check,
code import, code execution, hardware-readiness check, managed runner, shared
environment schema, workflow/DAG behavior, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/modern_manifest_preflight/basic_pyproject_preflight/`](../../tests/fixtures/modern_manifest_preflight/basic_pyproject_preflight/)

Implementation candidate:
[`../../implementation_candidates/modern_manifest_preflight/`](../../implementation_candidates/modern_manifest_preflight/)

The fixture preflights one approved qA chevron `pyproject.toml` manifest from
explicit prior context:

- prepared run context;
- declared modern `uv` environment context;
- explicit preflight request and approval id;
- caller-provided workspace root plus declared manifest-relative path.

The builder reads only the approved `pyproject.toml` path under the caller root.
It parses declared project name, `requires-python`, simple dependency names,
skipped unparsed dependency entries, and list-shaped dependency group names. It
compares declared dependency-group expectations with groups present in the
manifest and reports missing or malformed `requires-python`, malformed
dependency-group values, and missing declared groups as review findings.

It does not read lockfiles, resolve dependencies, run `uv`, synchronize package
state, install packages, inspect runtimes, import selected code, execute
selected code, probe hardware, or decide whether the run can start.

Raw JSON fixture input is validated into dataclass contract records before
projection. The contract validates exact top-level source shape, exact policy
shape, explicit approved operation, repository-safe managed identifiers,
non-path workspace-root label, prepared-context scope alignment, declared
environment alignment, declared `uv` manager, declared `pyproject.toml` path,
relative path syntax, exact non-operational claim shape, expected dependency
groups, and policy attention boundaries. This is not a shared environment
schema.

## What This Earned

The implementation candidate shows that Scopecat can perform the first narrow
approved environment read after review-bundle composition without increasing
authority to lockfile parsing, dependency resolution, dependency sync, or
package installation:

- require explicit approval for `modern_manifest_preflight`;
- read exactly one declared `pyproject.toml` path under a caller-provided root;
- parse only declared manifest summary facts with stdlib `tomllib`;
- compare manifest dependency groups with declared expectations;
- report unavailable manifests, malformed manifests, missing or malformed
  `requires-python`, malformed dependency-group values, and missing-group
  review findings;
- keep lockfile parsing, dependency resolution, dependency sync, package
  installation, runtime probing, code import, code execution, hardware probing,
  shared environment schema, managed runners, run-blocking decisions, and
  runnable-readiness claims out of scope.

## Boundary

This slice validates approved manifest preflight only.

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

Modern manifest preflight is useful after environment review bundle composition
because it gives an approved first read of the current manifest without folding
manifest parsing, dependency resolution, sync, install, runtime checks, and
readiness into one large authority jump.

The result remains a preflight summary, not an environment operation. Manifest
facts, missing or malformed `requires-python`, malformed dependency-group
values, and missing declared dependency groups remain review items. They do not
become dependency-resolution results, runtime compatibility results, hardware
readiness, runnable readiness, reproducibility, safety, or run-blocking claims.

## Follow-Up

Stop this slice at approved manifest preflight unless the next workflow needs
approved lockfile parsing, dependency resolution, dependency sync, or package
installation.

Likely follow-up slices should stay separate:

- additional preflight fixtures for unavailable and malformed manifests;
- approved lockfile preflight, if lockfile graph summaries become necessary;
- approved dependency resolution after manifest and lockfile preflight
  authority is separately validated;
- approved dependency sync only after resolution/sync intent and mutation
  boundaries are validated;
- execution or managed-runner slices only after environment operation
  authority, hardware boundaries, and run lifecycle are separately validated.
