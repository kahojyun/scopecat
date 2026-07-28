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

Each `scopecat.toml` names the control-plane application and, when devices are
configured, a separately importable worker backend:

```toml
[lab]
application = "my_lab.application:create_application"
instrument_backend = "my_lab.backend:create_backend"
```

```python
from pathlib import Path

from scopecat.application import LabApplication
from my_lab import (
    build_experiment_system,
    build_initial_config,
)


def create_application(project: Path) -> LabApplication:
    return LabApplication(
        bootstrap_config=lambda: build_initial_config(project),
        build_experiment_system=lambda accepted_config, instrument_catalog: (
            build_experiment_system(
                accepted_config,
                instrument_catalog=instrument_catalog,
                project=project,
            )
        ),
    )
```

```python
from pathlib import Path

from scopecat.sdk.instruments import InstrumentBackend
from my_lab.drivers import LabProvider


def create_backend(project: Path) -> InstrumentBackend:
    return InstrumentBackend(provider=LabProvider.from_project(project))
```

Both callables accept the resolved project `Path`. The bootstrap factory is a
lazy seed used only for an empty registry. Notebook planning receives the
accepted snapshot and the daemon-resolved contract catalog. Backend code,
transports, codecs, and drivers are imported and constructed only in the
long-lived instrument worker.

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
