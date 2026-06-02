# Repository Agent Instructions

- Follow narrower `AGENTS.md` files when working under their directories.
- When behavior or documented contracts change, update the affected docs,
  implementation, fixtures, tests, and expected outputs together. Before fixing
  review feedback, classify whether it changes contract, implementation, or
  wording.
- Fixtures should be small, explicit, and repository-safe by default. Required
  input fields must appear in the fixture or test case, not be silently supplied
  by helpers. Repository-safe fixture artifacts must not contain real secrets,
  real private paths, real hostnames, real lab/user/customer identifiers,
  tokens, or accidental local filesystem leaks; synthetic sensitive-shaped
  examples may appear only when intentionally testing boundary behavior.
- Do not treat every discovery fixture, expected output, review summary, or
  local Scopecat UI surface as portable/public/export output. Runtime redaction
  is required only at declared portable/public/export boundaries, or when an
  artifact is exported outside the repository or local workspace, published,
  externally shared, materialized as a portable handoff artifact, or otherwise
  generated to be carried away. When changing public output, sharing
  boundaries, fixtures, expected outputs, or generated artifacts, first
  classify the artifact boundary using
  `docs/discovery/policies/artifact-boundary-and-redaction.md`; new or changed
  discovery summaries/expected outputs should record their posture as
  `internal_validation_summary`, `review_summary`, or `export/package` in the
  candidate README, validation result, or summary policy field. Ordinary
  internal governance, architecture, route-index, decision, and navigation
  Markdown documents do not need artifact posture labels unless they are
  themselves promoted to public/export documentation or define a generated
  artifact boundary. Then audit for the classified boundary:
  repository-safety for fixtures, projection and managed-reference validation
  for review summaries, and runtime redaction for portable/export artifacts.
  Label auditing for repository fixtures is human repository-safety review, not
  runtime DLP or schema validation, unless the slice explicitly declares a
  redaction policy surface.
- Keep redaction scope explicit. Strictly validate Scopecat-managed references
  such as paths, source identities, package-relative references, relation
  targets, external-root displays, and materialization destinations when a
  slice claims to own or transform them. Treat user labels, display names,
  notes, and descriptions as free text unless a slice explicitly accepts a
  redaction policy surface; repository fixtures should remain reviewed for safe
  free text, but discovery candidates should not grow broad runtime redaction
  or DLP-style scanning for labels by default.
- Keep prototypes within their stated boundary; static-analysis prototypes must
  not execute analyzed fixture or source code.
- Do not generalize architecture, ownership, or reusable contracts from one
  validation slice unless an accepted decision states that scope.
- Use `uv` for Python environment and dependency management. This repository
  uses the `uv_build` backend with a `src/scopecat` package layout. Keep
  research, fixtures, and implementation candidates outside the installable
  package boundary unless a narrower accepted decision promotes them.
- Use stdlib `unittest` for Python tests unless a narrower instruction says
  otherwise. Run tests with `uv run python -m unittest discover -s tests`; do
  not assume `pytest` is available.
- Run repository lint and format checks with `uv run ruff check .` and
  `uv run ruff format --check .`. Apply formatting with
  `uv run ruff format .` when needed.
