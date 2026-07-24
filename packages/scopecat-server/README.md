# Scopecat server

`scopecat-server` provides the local FastAPI and SSE transport plus the default
SQLite daemon runtime. Point it at a lab project containing `scopecat.toml`:

```console
uv run scopecat config check ./my-lab
uv run scopecat start ./my-lab
uv run scopecat open ./my-lab
```

`config check` resolves and validates the application's bootstrap snapshot
without starting a daemon or writing the configuration registry.

The daemon stores its database and immutable objects under
`my-lab/.scopecat`, serves the bundled GUI, and selects an available loopback
port recorded in `.scopecat/daemon.json`. The GUI provides live status, run
browsing, resource state, durable events, analyses, and data previews.
The GUI reconnects through the daemon's replayable SSE event stream; it does
not keep a separate database.

The GUI also reads the daemon-owned configuration registry and the parameter
proposals attached to each run. Imports create immutable entries; activation,
review, rollback, and approved-candidate promotion are explicit
generation-checked commands.

The manifest names one importable application factory:

```toml
[lab]
application = "my_lab.application:create_application"
```

Managed experiments need a process-local catalog and a system builder.
Notebook scratch execution imports the same user-owned composition root:

```python
from pathlib import Path

from scopecat import LabApplication
from my_lab import build_catalog, build_initial_config, build_system


def create_application(project: Path) -> LabApplication:
    return LabApplication(
        bootstrap_config=lambda: build_initial_config(project),
        catalog=build_catalog(),
        build_system=lambda accepted_config: build_system(
            accepted_config,
            project=project,
        ),
    )
```

The named callable must accept the resolved project `Path` and return
`LabApplication`. The daemon adds both the project root and its optional `src/`
directory to the import path, so flat modules and standard `src` layouts work
without an editable install. Catalog identities are explicit `(id, version)`
pairs.

The builder receives the exact accepted snapshot selected for each run. The
application's `bootstrap_config` seeds daemon state once, and the daemon
registry is authoritative afterward. Notebook code discovers the same
application with `sc.open_project("./my-lab").connect()`.

`LabApplication.bootstrap_config` is a seed, not a mutable runtime setting. The
daemon calls the factory, validates, registers, and activates its result only
when the registry is empty. Loading the application from a notebook does not
resolve the seed. Once an operator imports or activates another entry,
restarting the daemon preserves that selection.

Only one daemon can own a lab instance. A process-owner lock rejects a second
daemon; there are no per-run filesystem locks or multi-writer repositories.
SQLite transactions serialize durable changes inside the owner process, and
delegated executors use renewable, generation-fenced leases.

The default server is intentionally local and same-user: it binds to loopback,
checks trusted host names, and does not provide remote authentication. Lost
executors are fenced on restart and their resources stay quarantined until an
operator releases, requeues, or aborts the run from the GUI or Python client.

Tests can construct `LocalDaemonRuntime` with a temporary project directory or
pass another `DaemonBackend` to `create_app`.
