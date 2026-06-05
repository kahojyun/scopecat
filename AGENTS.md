# Repository Agent Instructions

- Follow narrower `AGENTS.md` files when working under their directories.
- Apply governance rules by maturity and artifact boundary. Full coordination
  is required for accepted behavior, documented contracts, public/export
  boundaries, new implementation owners, and production-readiness promotion.
  Small bounded-discovery or prototype-owner edits should use the nearest
  relevant subset instead of expanding project-wide ceremony.
- When accepted behavior or documented contracts change, update the affected
  docs, implementation, fixtures, tests, and expected outputs together.
- Keep fixtures small, explicit, and repository-safe. Required input fields
  must appear in the fixture or test case, not be silently supplied by helpers.
- Apply `docs/architecture/artifact-boundary-and-redaction.md` only when work
  changes a declared public, sharing, review-summary, package/export, or
  generated-artifact boundary. Ordinary fixtures, expected outputs, local UI,
  governance docs, architecture docs, owner indexes, and decision docs are not
  portable/public/export output by default.
- Keep prototypes within their stated boundary; static-analysis prototypes must
  not execute analyzed fixture or source code.
- Do not generalize architecture, ownership, or reusable contracts from one
  validation artifact, fixture family, or prototype owner unless an accepted
  decision states that scope.
- Use `uv` for Python environment and dependency management. This repository
  uses the `uv_build` backend with a `src/scopecat` package layout. Keep
  research, spikes, fixtures, and historical candidate material outside the
  installable package boundary unless a narrower accepted decision promotes
  them.
- Use stdlib `unittest` for Python tests unless a narrower instruction says
  otherwise. Run tests with `uv run python -m unittest discover -s tests`; do
  not assume `pytest` is available.
- Run repository lint and format checks with `uv run ruff check .` and
  `uv run ruff format --check .`. Apply formatting with
  `uv run ruff format .` when needed.
