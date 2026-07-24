# Scopecat

<p align="center"><img src="assets/branding/app-icon.svg" alt="Scopecat app icon" width="160"></p>

Scopecat is a local-first Python workspace for describing experiments and
keeping their accepted inputs, execution evidence, measurements, analysis, and
candidate configuration changes together.

The long-term direction is captured in the
[project charter](docs/project-charter.md) and the
[experiment execution semantics](docs/experiment-execution-model.md). The
[workspace daemon model](docs/workspace-daemon.md) defines durable ownership
across the GUI, notebooks, and executors.
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

Start one daemon for a workspace. It owns the SQLite database and immutable
object store and serves the local GUI at <http://127.0.0.1:8765>:

```sh
uv run scopecatd --workspace ./my-workspace
```

Connect from Python or a notebook:

```python
import scopecat as sc

with sc.connect() as workspace:
    print(workspace.health())
    print(workspace.runs())
```

The daemon can execute registered experiments itself, or a notebook can execute
transient scratch code while sending every durable effect back to the daemon.
For managed execution, start it with a lab definition and configuration:

```sh
uv run scopecatd \
  --workspace ./my-workspace \
  --definition my_lab.daemon:daemon \
  --config-profile ./config-profile.json
```

See the [workspace daemon model](docs/workspace-daemon.md) and
[`scopecat-server` setup](packages/scopecat-server/README.md), then continue
with [the quantum examples](examples/quantum/README.md). The package READMEs
describe the smaller public entry points for
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
