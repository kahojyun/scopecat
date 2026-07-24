# Scopecat

Scopecat is a local-first, domain-neutral experiment authoring, planning,
execution, and measurement package. A user project owns its Python code,
`scopecat.toml`, and Python-constructed bootstrap configuration; the resident
daemon owns accepted configuration and run records.

Open the project and connect its high-level notebook client:

```python
import scopecat as sc

project = sc.open_project("./my-lab")
with project.connect() as lab:
    health = lab.health()
    runs = lab.runs()
```

Project discovery loads the same version-controlled `LabApplication` used by
the daemon. The application supplies an optional bootstrap factory, a catalog,
and a config-aware system builder; planning always passes it the accepted
config snapshot selected for that run.

The Python application may provide the initial immutable snapshot when the
registry is empty. Later imports, activations, analysis, proposal review, and
run data all go through the daemon and survive notebook and daemon restarts.

Transient scratch code can stay in the notebook when a closure or interactive
object cannot be reconstructed reliably in the daemon:

```python
with project.connect() as lab:
    run = lab.prepare(scratch_invocation).run()
```

Scratch planning and Python closures stay in the notebook process. Admission,
resource ownership, measurements, terminal state, saved analysis, proposal
review, and configuration changes still go through the daemon.

`sc.connect()` remains the lower-level daemon transport client for operator and
infrastructure workflows such as exact catalog submission, event replay, and
attention resolution. Normal notebook code should start from
`sc.open_project(...)`.

See the [repository README](../../README.md) for the runnable introduction and
development commands, and the
[daemon design](../../docs/lab-daemon.md) for ownership and fencing
semantics. Implementation contracts and rationale are documented in the owning
modules' docstrings.
