# Repository Agent Instructions

- Follow narrower `AGENTS.md` files when working under their directories.
- Apply governance rules by maturity and artifact boundary. Full coordination
  is required for accepted behavior, documented contracts, public/export
  boundaries, new implementation owners, and production-slice promotion. Small
  discovery-local or route-local prototype edits should use the nearest
  relevant subset instead of expanding project-wide ceremony.
- When accepted behavior or documented contracts change, update the affected
  docs, implementation, fixtures, tests, and expected outputs together. Before
  fixing review feedback, classify whether it changes contract,
  implementation, or wording.
- Fixtures should be small, explicit, and repository-safe by default. Required
  input fields must appear in the fixture or test case, not be silently supplied
  by helpers. Repository-safe fixture artifacts must not contain real secrets,
  real private paths, real hostnames, real lab/user/customer identifiers,
  tokens, or accidental local filesystem leaks; synthetic sensitive-shaped
  examples may appear only when intentionally testing boundary behavior.
- Classify artifact boundaries using
  `docs/architecture/artifact-boundary-and-redaction.md` only when
  changing public output, sharing boundaries, review summaries, package/export
  artifacts, or generated artifacts that define or cross a declared boundary.
  Do not treat ordinary discovery fixtures, expected outputs, local UI surfaces,
  governance docs, architecture docs, route indexes, or decision docs as
  portable/public/export output by default.
- Keep redaction scope explicit. Repository fixtures need human
  repository-safety review. Review summaries need managed-reference validation.
  Portable/export artifacts need runtime redaction. Strictly validate
  Scopecat-managed references such as paths, source identities,
  package-relative references, relation targets, external-root displays, and
  materialization destinations when work owns or transforms them. Treat user
  labels, display names, notes, and descriptions as free text unless the work
  explicitly accepts a redaction policy surface.
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
