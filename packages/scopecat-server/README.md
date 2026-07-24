# Scopecat server

`scopecat-server` provides the local FastAPI and SSE transport plus the default
SQLite daemon runtime. Start it with:

```console
uv run scopecatd --workspace ./my-workspace
```

The daemon stores its database and immutable objects under
`my-workspace/.scopecat`, serves the bundled GUI, and listens only on
`127.0.0.1:8765` by default. Open <http://127.0.0.1:8765> for live status, run
browsing, resource state, durable events, and bounded measurement previews.
The GUI reconnects through the daemon's replayable SSE event stream; it does
not keep a second workspace database.

A daemon started without a definition still supports GUI reads and delegated
notebook/scratch execution. Managed experiments need a process-local catalog
and hardware system. Load them from a small application definition:

```python
from pathlib import Path

from my_lab import build_catalog, build_system
from scopecat.config.profiles import load_config_profile
from scopecat_server import DaemonDefinition


def daemon(workspace: Path) -> DaemonDefinition:
    return DaemonDefinition(
        catalog=build_catalog(),
        system=build_system(workspace),
        active_config=load_config_profile(workspace / "config-profile.json"),
    )
```

```console
uv run scopecatd \
  --workspace ./my-workspace \
  --definition my_lab.daemon:daemon
```

The module must be importable, and the named callable must accept the resolved
workspace `Path` and return `DaemonDefinition`. Catalog identities are explicit
`(id, version)` pairs.

Instead of returning `active_config` from the definition, pass a profile file
on the command line:

```console
uv run scopecatd \
  --workspace ./my-workspace \
  --definition my_lab.daemon:daemon \
  --config-profile ./config-profile.json
```

`--config-profile` takes precedence over `DaemonDefinition.active_config`.
Startup validates the snapshot, registers it under a content-derived identity,
and activates it. Reusing unchanged content is idempotent.

Only one daemon can own a workspace. A process-owner lock rejects a second
daemon; there are no per-run filesystem locks or multi-writer repositories.
SQLite transactions serialize durable changes inside the owner process, and
delegated executors use renewable, generation-fenced leases.

The default server is intentionally local and same-user: it binds to loopback,
checks trusted host names, and does not provide remote authentication. Lost
executors are fenced on restart and their resources stay quarantined until an
operator releases, requeues, or aborts the run from the GUI or Python client.

Embedders can construct `LocalDaemonRuntime` directly or pass another
`DaemonBackend` to `create_app`.
