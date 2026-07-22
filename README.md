# Scopecat

<p align="center"><img src="assets/branding/app-icon.svg" alt="Scopecat app icon" width="160"></p>

Scopecat is a local-first Python workspace for describing experiments and
keeping their accepted inputs, execution evidence, measurements, analysis, and
candidate configuration changes together.

The long-term direction is captured in the
[project charter](docs/project-charter.md) and the
[experiment execution semantics](docs/experiment-execution-model.md).
Implementation contracts and design rationale live beside the code that owns
them.

## Workspace

- `packages/scopecat`: domain-neutral authoring, planning, execution, data, and
  workspace APIs.
- `packages/scopecat-quantum`: hardware-independent quantum building blocks.
- `examples/quantum`: notebook-first examples and a local demonstration lab.
- `fixtures`: sample inputs shared by tests and examples.
- `docs`: long-term product direction.

## Start Here

The quantum learning path is the most complete runnable introduction:

```sh
uv run python examples/quantum/notebooks/getting_started/01_open_workspace.py
```

Continue with [the quantum examples](examples/quantum/README.md). The package
READMEs describe the smaller public entry points for
[`scopecat`](packages/scopecat/README.md) and
[`scopecat-quantum`](packages/scopecat-quantum/README.md).

## Development

Run the workspace checks from the repository root:

```sh
uv run pytest
uv run basedpyright
uv run ruff check packages examples
uv run ruff format --check packages examples
```
