# UV Sync Intent Candidate

This candidate validates one explicit `uv sync` command intent and projects the
bounded argv for review.

Summary posture: `review_summary`. The output is a command-intent summary, not
dependency resolution, dependency sync, package installation, process
execution, runtime compatibility, hardware readiness, run-start readiness, or a
portable/public/export artifact.

It can:

- validate an explicit approval id, approved operation, prepared run context, and declared
  `uv`/`pyproject.toml` environment reference;
- require the declared environment record to be `declared`, not already marked
  with review findings;
- validate a declared working directory path syntactically and require it to
  contain the declared `pyproject.toml`;
- require the declared lockfile reference to be `uv.lock` beside the declared
  `pyproject.toml`;
- require dependency-group intent to match the declared environment using
  normalized group names while preserving request and declared-environment
  spelling for review;
- construct a bounded argv of `uv sync --locked --no-default-groups` plus
  repeated `--group <name>` entries for declared uv dependency groups;
- keep the first operation policy explicit: include project dependencies,
  exclude uv default dependency groups, and construct argv with `--locked`;
  if a later executor runs the command, uv decides whether the lockfile would
  remain unchanged and reports failure.

It does not inspect the filesystem, read `pyproject.toml`, read `uv.lock`,
parse lockfiles, resolve dependencies, run `uv`, synchronize package state,
install, update, or remove packages, inspect runtimes, import or execute code,
probe hardware, define a shared environment-manager abstraction, define managed
runner behavior, make run-blocking decisions, or decide that a run can start.

The candidate uses slice-local dataclass contracts. These contracts are not a
shared environment schema and are not a Pixi/Conda-capable manager interface.
Future Pixi/Conda-capable managers should earn separate manager-specific
operation slices before any shared manager abstraction is extracted.
