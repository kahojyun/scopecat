# Scopecat

<p align="center"><img src="assets/branding/app-icon.svg" alt="Scopecat app icon" width="160"></p>

Scopecat is an early brownfield-friendly project for scientific measurement
workflows. It is designed to improve evidence, review, and handoff around
existing lab systems while leaving room for deeper migration when a workflow
proves the need.

Scopecat is in active development; current docs describe product direction,
evidence, and implementation boundaries rather than finalized product
commitments.

See `docs/product/direction.md` for product direction and `docs/README.md` for
the documentation workspace.

## Status

New project workspace.

## Documentation

Start with `docs/README.md`.

The documentation workspace is the long-lived project memory for product
analysis, research, engineering prototype boundaries, and future user
documentation.
It should not be treated as a finalized product specification.

## Development

This repository uses `uv` for local Python environment management and the
`uv_build` backend for the local installable `src/scopecat` package. The
repository still contains research documents, fixtures, and implementation
candidates outside the package boundary.

```sh
uv sync
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```
