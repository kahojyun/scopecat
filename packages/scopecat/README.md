# Scopecat

Scopecat is a local-first, domain-neutral experiment authoring, planning,
execution, and measurement package. Its notebook-facing entry point is the
lazy `scopecat` facade; laboratory integrations use the public instrument and
domain SDK boundaries.

Connect to the resident workspace daemon instead of opening its storage in the
notebook process:

```python
import scopecat as sc

with sc.connect() as workspace:
    health = workspace.health()
    runs = workspace.runs()
```

`DaemonWorkspace` also exposes catalog, run-detail, measurement, and durable
event reads. Runs whose executor was lost remain quarantined until
`resolve_attention(run_id, "release" | "requeue" | "abort")` records an
operator decision.

Use `submit_managed(registration_id, registration_version, request)` when the
daemon definition contains that exact catalog registration. Start the daemon
with an active configuration through `--config-profile`, or provide
`DaemonDefinition.active_config`. The daemon validates and activates that
snapshot, then plans, acquires resources, and executes the run.

Scratch code can stay in the notebook:

```python
with sc.connect() as workspace:
    manifest = workspace.run_scratch(
        invocation,
        config=config_snapshot,
        system=experiment_system,
    )
```

`run_scratch` plans and executes the transient Python invocation locally, but
admission, resource claims, measurements, evidence, and terminal state are
committed through the daemon. For an already planned run,
`execute_delegated(planned, ...)` provides the lower-level equivalent.

See the [repository README](../../README.md) for the runnable introduction and
development commands, and the
[daemon design](../../docs/workspace-daemon.md) for ownership and fencing
semantics. Implementation contracts and rationale are documented in the owning
modules' docstrings.
