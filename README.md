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

An installed distribution already contains the GUI. When running from a source
checkout, build the UI into its own ignored output directory:

```sh
cd apps/scopecat-ui
pnpm install --frozen-lockfile
pnpm run build
cd ../..
```

Create a runnable project with a local Python configuration source and a
hardware-free first scratch experiment:

```sh
uv run scopecat init ./my-lab
uv run scopecat config check ./my-lab
uv run scopecat start ./my-lab --static-dir apps/scopecat-ui/dist
uv run scopecat open ./my-lab
uv run python ./my-lab/notebooks/01_first_run.py
```

The generated `src/scopecat_lab/configuration.py` is ordinary version-controlled
Python. After editing it, compare and explicitly publish the result:

```sh
uv run scopecat config diff ./my-lab
uv run scopecat config apply ./my-lab --actor operator-name
uv run scopecat config export ./my-lab --output ./active-config.json
```

`diff` freshly evaluates the project source and compares it with the daemon
default. `apply` validates the same snapshot and records one immutable default
change; it does not make the daemon watch or rewrite Python. `export` produces
a complete JSON snapshot for review or backup, not a primary editing format.

The quantum example is the fuller local lab project. Its `scopecat.toml` and
Python application—including construction of its bootstrap snapshot—are
version controlled; one daemon owns its `.scopecat` state:

```sh
uv run scopecat config check examples/quantum
uv run scopecat start examples/quantum --static-dir apps/scopecat-ui/dist
uv run scopecat open examples/quantum
```

`config check` validates the version-controlled bootstrap source without
starting a daemon or creating project state. `start` selects an available
loopback port and records it inside the project, so the GUI and notebook client
discover the same daemon without a fixed URL. The GUI can browse immutable
configuration history, parameter values, runs, data, and saved analysis.
Run the notebook-style walkthrough in another terminal:

```sh
uv run python examples/quantum/notebooks/getting_started/01_open_project.py
uv run python examples/quantum/notebooks/getting_started/02_edit_config.py
uv run python examples/quantum/notebooks/getting_started/04_run_and_read_data.py
uv run python examples/quantum/notebooks/getting_started/07_rerun_candidate_config.py
```

The run appears live in the GUI and remains available to later notebooks.
Normal configuration changes are one intent: set an immutable revision as the
default, accept an analysis candidate, or undo to the previous default. The
daemon still records every revision, acceptance decision, and activation while
keeping entry ids and concurrency generations out of the ordinary workflow.
Verification runs are optional evidence rather than a prerequisite for
acceptance.

Explicitly local scratch code still executes in the notebook process when it
cannot be sent reliably to another process. Admission, resource ownership,
measurements, analysis, and configuration history are written only by the
daemon.

A normal lab project follows the same small shape:

```text
my-lab/
├── scopecat.toml
├── notebooks/
├── src/scopecat_lab/
│   ├── application.py
│   └── configuration.py
└── config/                  # optional external infrastructure inputs
```

See the [lab daemon model](docs/lab-daemon.md) and
[`scopecat-server` setup](packages/scopecat-server/README.md), then continue
with [the quantum examples](examples/quantum/README.md). The package READMEs
describe the smaller public entry points for
[`scopecat`](packages/scopecat/README.md) and
[`scopecat-quantum`](packages/scopecat-quantum/README.md).

## Development

Development and source-checkout workflows require Python 3.14 or newer.

Use `uv sync --group notebook` only when a local Jupyter kernel is needed.

Run the repository checks from the repository root:

```sh
uv run pytest
uv run basedpyright
uv run ruff check packages examples docs scripts
uv run ruff format --check packages examples docs scripts
```

To assemble release artifacts without modifying either source tree:

```sh
cd apps/scopecat-ui
pnpm run build
cd ../..
uv run python scripts/build_server_distribution.py
```
