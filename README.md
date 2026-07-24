# Scopecat

<p align="center"><img src="assets/branding/app-icon.svg" alt="Scopecat app icon" width="160"></p>

Scopecat is a local-first Python control plane for describing experiments and
keeping their accepted inputs, execution evidence, measurements, analysis, and
candidate configuration changes together.

The long-term direction is captured in the
[project charter](docs/project-charter.md) and the
[experiment execution semantics](docs/experiment-execution-model.md). The
[lab daemon model](docs/lab-daemon.md) defines durable ownership
across the GUI, notebooks, and executors.
Implementation contracts and design rationale live beside the code that owns
them.

## Repository

- `packages/scopecat`: domain-neutral authoring, planning, execution, data, and
  daemon client APIs.
- `packages/scopecat-quantum`: hardware-independent quantum building blocks.
- `examples/quantum`: notebook-first examples and a local demonstration lab.
- `fixtures`: test-only inputs; runnable projects own their bootstrap config.
- `docs`: long-term product direction.

## Start Here

The quantum example is a complete local lab project. Its `scopecat.toml` and
Python application—including construction of its bootstrap snapshot—are
version controlled; one daemon owns its `.scopecat` state:

```sh
uv run scopecat config check examples/quantum
uv run scopecat start examples/quantum
uv run scopecat open examples/quantum
```

`config check` validates the version-controlled bootstrap source without
starting a daemon or creating project state. `start` selects an available
loopback port and records it inside the project, so the GUI and notebook client
discover the same daemon without a fixed URL. The GUI can browse immutable
configuration history and turn scalar or table edits into a reviewed candidate;
registration and activation remain separate actions.
Run the notebook-style walkthrough in another terminal:

```sh
uv run python examples/quantum/notebooks/getting_started/01_open_project.py
uv run python examples/quantum/notebooks/getting_started/04_run_and_read_data.py
```

The run appears live in the GUI and remains available to later notebooks.
Explicitly local scratch code still executes in the notebook process when it
cannot be sent reliably to another process. Admission, resource ownership,
measurements, analysis, and configuration history are written only by the
daemon.

A normal lab project follows the same small shape:

```text
my-lab/
├── scopecat.toml
├── config/
├── notebooks/
└── src/my_lab/
```

See the [lab daemon model](docs/lab-daemon.md) and
[`scopecat-server` setup](packages/scopecat-server/README.md), then continue
with [the quantum examples](examples/quantum/README.md). The package READMEs
describe the smaller public entry points for
[`scopecat`](packages/scopecat/README.md) and
[`scopecat-quantum`](packages/scopecat-quantum/README.md).

## Development

Run the repository checks from the repository root:

```sh
uv run pytest
uv run basedpyright
uv run ruff check packages examples
uv run ruff format --check packages examples
```
