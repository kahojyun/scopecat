# Scopecat Server

Local FastAPI and SSE transport plus the default SQLite daemon runtime.
Published distributions include the project GUI; source checkouts may use the
Vite development server or pass `apps/scopecat-ui/dist` with `--static-dir`.

From the repository root:

```console
uv run scopecat init ./my-lab
uv run scopecat config check ./my-lab
uv run scopecat start ./my-lab --static-dir apps/scopecat-ui/dist
uv run scopecat open ./my-lab
uv run python ./my-lab/notebooks/01_first_run.py
```

`init` creates a project without replacing existing files. `config check`
validates its bootstrap source without starting a daemon or writing project
state. Configuration reconciliation commands and the complete runnable
walkthrough live in the [repository README](../../README.md).

Each `scopecat.toml` names one importable application factory:

```toml
[lab]
application = "my_lab.application:create_application"
```

```python
from pathlib import Path

from scopecat.application import LabApplication
from my_lab import build_initial_config, build_system


def create_application(project: Path) -> LabApplication:
    return LabApplication(
        bootstrap_config=lambda: build_initial_config(project),
        build_system=lambda accepted_config: build_system(
            accepted_config,
            project=project,
        ),
    )
```

The callable accepts the resolved project `Path`. The bootstrap factory is a
lazy seed used only for an empty registry; the system builder receives the
accepted snapshot selected for each run.

Only one daemon owns a project. It stores SQLite and immutable objects below
`.scopecat`, records its loopback endpoint in `.scopecat/daemon.json`, and
serves the replayable event stream used by GUI and notebook clients. See the
[daemon model](../../docs/lab-daemon.md) for ownership, fencing, quarantine,
and security boundaries.

For a bundled source-checkout preview:

```console
cd apps/scopecat-ui
pnpm run build
cd ../..
uv run python scripts/build_server_distribution.py
```

Tests may construct `LocalDaemonRuntime` with a temporary project or pass a
custom `DaemonApplication` to `create_app`.
