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
registry is empty. Later default changes, analysis, acceptance decisions, and
run data all go through the daemon and survive notebook and daemon restarts.
Project tooling keeps source reconciliation explicit:

```sh
scopecat config diff ./my-lab
scopecat config apply ./my-lab --actor operator-name
scopecat config export ./my-lab --output ./active-config.json
```

The CLI freshly evaluates and validates Python configuration source. The
daemon never watches or rewrites it; exported JSON is a generated snapshot for
review or backup.

Routine configuration work uses typed intent APIs:

```python
with project.connect() as lab:
    draft = lab.edit_config().replace_scalar("repetitions", sc.Quantity(256, "count"))
    changed = lab.config.set_default(draft, note="increase averaging")

    analysis = run.analysis("fit").propose(...)
    accepted = lab.config.accept(analysis, note="fit passed")
    restored = lab.config.undo(note="restore the previous default")
```

These calls retain immutable history and provenance without asking notebook
code for registry entry ids or concurrency generations. Explicit import,
review, activation, and generation-checked rollback remain available for
operator and diagnostic workflows.

Transient scratch code can stay in the notebook when a closure or interactive
object cannot be reconstructed reliably in the daemon:

```python
with project.connect() as lab:
    run = lab.prepare(scratch_invocation).run()
```

Scratch planning and Python closures stay in the notebook process. Admission,
resource ownership, measurements, terminal state, saved analysis, acceptance
decisions, and configuration changes still go through the daemon.

`sc.connect()` remains the lower-level daemon transport client for operator and
infrastructure workflows such as exact catalog submission, event replay, and
attention resolution. Normal notebook code should start from
`sc.open_project(...)`.

See the [repository README](../../README.md) for the runnable introduction and
development commands, and the
[daemon design](../../docs/lab-daemon.md) for ownership and fencing
semantics. Implementation contracts and rationale are documented in the owning
modules' docstrings.
