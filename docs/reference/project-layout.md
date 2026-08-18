# Project layout and manifest

`scopecat init my-lab` creates this minimal project:

```text
my-lab/
├── scopecat.toml
├── notebooks/
│   └── 01_first_run.py
└── src/scopecat_lab/
    ├── __init__.py
    ├── application.py
    ├── backend.py
    └── configuration.py
```

Projects may add a `config/` directory for external, version-controlled
infrastructure inputs. Runtime state lives in `.scopecat/` and is owned by the
daemon rather than edited by users.

## Manifest

`scopecat.toml` identifies daemon bootstrap, project application, and instrument
backend factories:

```toml
[lab]
bootstrap = "scopecat_lab.application:create_bootstrap"
application = "scopecat_lab.application:create_application"
instrument_backend = "scopecat_lab.backend:create_backend"
```

Both values use `MODULE:CALLABLE` syntax. Project discovery searches at or above
the supplied path and makes the project's `src` directory importable.

## Source ownership

- `application.py` exports a lightweight bootstrap factory for the daemon and a
  separate full application factory for notebooks and the project worker.
- `backend.py` composes worker-only instrument providers and drivers.
- `configuration.py` builds the bootstrap configuration used only while the
  daemon registry is empty.
- `notebooks/` contains user-owned interactive workflows and scripts.

After initialization, these are application source files: edit, test, and
version them with the rest of the lab project. Use the
[configuration review workflow](../how-to/manage-configuration.md) to publish
configuration changes explicitly.

Keep procedure, schedule, calibration, publication, and system-builder imports
inside the full application factory. Importing the bootstrap factory must not
load those user execution callbacks into the daemon process.
