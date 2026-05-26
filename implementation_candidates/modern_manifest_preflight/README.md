# Modern Manifest Preflight Candidate

This candidate reads one explicitly approved `uv`/`pyproject.toml` file and
projects declared manifest facts for review and comparison.

Summary posture: `review_summary`. The output is a narrow preflight summary,
not dependency resolution, dependency sync, package installation, runtime
compatibility, hardware readiness, or run-start readiness.

This is a manager-specific review projection, not Scopecat's general
environment abstraction. `uv` remains the authority for resolution, lock
interpretation, sync, and installation; future managers such as Pixi should
earn separate projection and operation slices before any shared manager
contract is generalized.

It can:

- validate an explicit preflight approval record, prepared run context, and
  declared `uv`/`pyproject.toml` environment reference;
- read only the declared `pyproject.toml` path under a caller-provided
  workspace root;
- parse declared project metadata, simple dependency names, `requires-python`
  syntax posture, a synthetic `default` group from list-shaped
  `[project].dependencies`, and list-shaped `[dependency-groups]` names using
  stdlib `tomllib`;
- compare declared dependency-group expectations with groups present in the
  manifest using normalized dependency-group names while preserving original
  names for review display;
- report manifest unavailable, read failed, parse failed, missing or malformed
  `requires-python`, malformed dependency-group values, normalized
  dependency-group-name collisions, and missing declared dependency-group
  review findings.

It does not read lockfiles, resolve dependencies, run dependency sync, install,
update, or remove packages, inspect interpreters or installed packages, import
or execute code, contact hardware, define a shared environment schema, define
managed-runner behavior, make run-blocking decisions, or decide that a run can
start.

The candidate uses slice-local dataclass contracts and policy attention
matrices. These contracts are not a shared environment schema.
