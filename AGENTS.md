# Repository Agent Instructions

- Follow narrower `AGENTS.md` files when working under their directories.
- When behavior or documented contracts change, update the affected docs,
  implementation, fixtures, tests, and expected outputs together. Before fixing
  review feedback, classify whether it changes contract, implementation, or
  wording.
- Fixtures should be small, explicit, and public-safe by default. Required input
  fields must appear in the fixture or test case, not be silently supplied by
  helpers.
- When changing public output, sharing boundaries, fixtures, or generated
  artifacts, audit identifiers, labels, relation targets, metadata,
  Markdown/JSON output, and payload/code-derived text.
- Keep redaction scope explicit. Strictly validate Scopecat-managed references
  such as paths, source identities, package-relative references, relation
  targets, external-root displays, and materialization destinations. Treat user
  labels, display names, notes, and descriptions as free text unless a slice
  explicitly accepts a redaction policy surface; public fixtures should remain
  reviewed for safe free text, but discovery candidates should not grow broad
  runtime redaction or DLP-style scanning for labels by default.
- Keep prototypes within their stated boundary; static-analysis prototypes must
  not execute analyzed fixture or source code.
- Do not generalize architecture, ownership, or reusable contracts from one
  validation slice unless an accepted decision states that scope.
- Use `uv` for Python environment and dependency management. This repository is
  currently configured as a non-package project; do not add packaging or
  publishing metadata unless the project explicitly moves beyond research,
  fixtures, and implementation candidates.
- Use stdlib `unittest` for Python tests unless a narrower instruction says
  otherwise. Run tests with `uv run python -m unittest discover -s tests`; do
  not assume `pytest` is available.
- Run repository hooks with `uv run prek run --all-files`.
