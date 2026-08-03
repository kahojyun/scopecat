# Scopecat

<p align="center"><img src="assets/branding/app-icon.svg" alt="Scopecat app icon" width="160"></p>

Scopecat is a local-first Python toolkit for controlling laboratory
instruments, running scans, and keeping measurements and their context
together. It is designed to fit into notebooks and existing Python workflows
without making ordinary experiments more complicated than ad hoc scripts or
small internal scan frameworks.

The [project charter](docs/project-charter.md) defines the current product
priorities. The execution, daemon, and instrument-control documents describe
the current architecture; they are implementation choices rather than product
requirements and may be simplified to improve the primary workflows.
Implementation contracts and local design rationale live beside the code that
owns them.

## Repository

- `packages/scopecat`: domain-neutral authoring, planning, execution, data, and
  daemon client APIs.
- `packages/scopecat-instruments`: minimal real SCPI drivers and coupled
  virtual laboratory devices.
- `packages/scopecat-quantum`: hardware-independent quantum building blocks.
- `examples/instruments`: hardware-free GUI and notebook direct-control tour.
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
hardware-free first experiment:

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
Python application and backend—including construction of its bootstrap
snapshot and virtual devices—are version controlled; one daemon owns its
`.scopecat` state:

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
uv run python examples/quantum/notebooks/calibration/01_drag_beta.py
```

The walkthrough runs the supported DRAG-beta calibration from measurement
through candidate acceptance, production use, and undo. The daemon records
every immutable revision, acceptance decision, and activation while keeping
entry ids and concurrency generations out of the ordinary workflow.

For a hardware-free instrument-control tour instead, start
`examples/instruments` and open the **Instruments** workspace:

```sh
uv run scopecat start examples/instruments --static-dir apps/scopecat-ui/dist
uv run scopecat open examples/instruments
uv run python examples/instruments/notebooks/01_direct_control.py
```

Its coupled virtual DC source, temperature monitor, RF source, and VNA use the
same interface and session APIs as real devices.

Locally authored Python closures still execute in the notebook process when
they cannot be sent reliably to another process. Admission, resource ownership,
measurements, analysis, and configuration history are written only by the
daemon.

A normal lab project follows the same small shape:

```text
my-lab/
├── scopecat.toml
├── notebooks/
├── src/scopecat_lab/
│   ├── application.py
│   ├── backend.py
│   └── configuration.py
└── config/                  # optional external infrastructure inputs
```

See the [lab daemon model](docs/lab-daemon.md) and
[`scopecat-server` setup](packages/scopecat-server/README.md), then continue
with [the quantum examples](examples/quantum/README.md). The
[measurement data workflow](docs/measurement-data.md) covers explicit point
rows, ragged results, notebook slicing, ecosystem exports, and automatic GUI
plots. The package READMEs
describe the smaller public entry points for
[`scopecat`](packages/scopecat/README.md) and
[`scopecat-instruments`](packages/scopecat-instruments/README.md), and
[`scopecat-quantum`](packages/scopecat-quantum/README.md).

## Development

Development and source-checkout workflows require Python 3.14 or newer.

Use `uv sync --group notebook` only when a local Jupyter kernel is needed.

Run the repository checks from the repository root:

```sh
uv run pytest
uv run --package scopecat --extra data pytest packages/scopecat/tests/measurements/test_dataset.py
uv run basedpyright
uv run lint-imports
uv run ruff check packages examples docs scripts
uv run ruff format --check packages examples docs scripts
```

The default test run includes all package tests and one end-to-end quantum
first-use slice. Run the complete demo suite explicitly with
`uv run pytest examples/quantum/tests examples/quantum/support/tests`.

To assemble release artifacts without modifying either source tree:

```sh
cd apps/scopecat-ui
pnpm run build
cd ../..
uv run python scripts/build_server_distribution.py
```
