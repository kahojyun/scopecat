# Scopecat server

`scopecat-server` provides the local FastAPI and SSE transport plus the default
SQLite daemon runtime. Published distributions include the project GUI. In a
source checkout, use `--api-only` with the Vite development server, or pass a
built `apps/scopecat-ui/dist` with `--static-dir`.

Create a runnable starter project or point it at an existing project
containing `scopecat.toml`:

```console
uv run scopecat init ./my-lab
uv run scopecat config check ./my-lab
uv run scopecat start ./my-lab --static-dir apps/scopecat-ui/dist
uv run scopecat open ./my-lab
uv run python ./my-lab/notebooks/01_first_run.py
```

`init` writes a local `src/scopecat_lab` application, an editable Python
configuration source with one typed parameter, and a hardware-free scratch
experiment. It preflights every owned path and never replaces an existing
project file.

`config check` resolves and validates the application's bootstrap snapshot
without starting a daemon or writing the configuration registry.

After editing the Python source, reconcile it explicitly with the running
daemon:

```console
uv run scopecat config diff ./my-lab
uv run scopecat config apply ./my-lab --actor operator-name
uv run scopecat config export ./my-lab --output ./active-config.json
```

`diff` and `apply` evaluate the source in the CLI process; the daemon does not
watch or execute changing source automatically. `apply` uses the same
intent-oriented, atomic default operation as notebooks. `export` writes the
complete daemon default as generated JSON and refuses to overwrite by default.
These project-management commands use the selected project's recorded daemon
instead of a generic `SCOPECAT_DAEMON_URL` override.

The daemon stores its database and immutable objects under
`my-lab/.scopecat`, serves the bundled GUI, and selects an available loopback
port recorded in `.scopecat/daemon.json`. The GUI provides live status, run
browsing, resource state, durable events, analyses, and data previews.
The GUI reconnects through the daemon's replayable SSE event stream; it does
not keep a separate database.

The GUI also reads the daemon-owned configuration registry and the parameter
proposals attached to each run. Routine actions are phrased as **Set as
default**, **Accept as default**, and **Undo**. The daemon implements them with
immutable entries, durable human or automatic-policy acceptance evidence, and
generation-checked activation. Explicit import, registration, review, and
activation remain available as lower-level operator commands. A dedicated
verification run is optional evidence, not an activation prerequisite.

The manifest names one importable application factory:

```toml
[lab]
application = "my_lab.application:create_application"
```

Notebook execution imports the user-owned composition root for its
configuration-aware system builder:

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

The named callable must accept the resolved project `Path` and return
`LabApplication`. The daemon adds both the project root and its optional `src/`
directory to the import path, so flat modules and standard `src` layouts work
without an editable install.

The notebook-side builder receives the exact accepted snapshot selected for
each run. The application's `bootstrap_config` seeds daemon state once, and the
daemon registry is authoritative afterward. Notebook code discovers the
application with `sc.open_project("./my-lab").connect()`.

`LabApplication.bootstrap_config` is a seed, not a mutable runtime setting. The
daemon calls the factory, validates, registers, and activates its result only
when the registry is empty. Loading the application from a notebook does not
resolve the seed. Once an operator imports or activates another entry,
restarting the daemon preserves that selection.

Only one daemon can own a lab instance. A process-owner lock rejects a second
daemon. SQLite transactions serialize durable changes inside the owner process,
and executors use renewable leases with unique fencing identities.

The default server is intentionally local and same-user: it binds to loopback,
checks trusted host names, and does not provide remote authentication. Lost
executors are fenced on restart and their resources stay quarantined until an
operator releases or aborts the run from the GUI or Python client. An abandoned
run is not resumed: after reconciling external state, the operator submits a
new run.

Tests can construct `LocalDaemonRuntime` with a temporary project directory or
pass another `DaemonApplication` to `create_app`, exposing separate
configuration, run, and executor services.
