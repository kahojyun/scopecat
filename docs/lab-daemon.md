# Lab Daemon

Scopecat has one durable writer per lab instance: a long-running local daemon.
GUI and Python processes are clients, even when Python executes an experiment
itself.

```text
GUI ─────────────────┐
                     ├─ HTTP + SSE ─ daemon ─ SQLite + object store
notebook client ─────┘                    │
  └─ delegated executor ─ fenced effects─┘
```

The daemon owns admission, run state, resource claims, executor leases,
configuration activation, event ordering, and every durable write. SQLite
transactions provide concurrency control inside that boundary. Content bytes
remain in an immutable SHA-256 object store so large values do not inflate the
control database. Clients never open either store.

## Execution modes

There are two modes with the same durable admission boundary:

- **Managed**: the daemon resolves a versioned catalog registration, plans it,
  claims resources, and executes it in the daemon process. The daemon
  application supplies the process-local catalog and config-aware system
  builder. Planning resolves the configuration snapshot from the daemon-owned
  registry and builds the matching `ExperimentSystem`.
- **Delegated**: a notebook keeps its transient `RunProgram`, Python closures,
  and hardware provider, while the daemon admits the plan and persists every
  effect.
  Renewable executor leases carry a generation fencing token, so an expired or
  superseded notebook cannot continue writing.

Admission and resource claims are durable before hardware access in both
modes. A delegated executor publishes its running manifest while acquiring its
lease; all later journal, measurement, collection, payload, recovery, and
terminal commands carry the lease identity and generation. Lease validation,
the effect receipt, and its durable event commit in one SQLite transaction.

`sc.open_project(...).connect()` returns the normal notebook `LabClient`. It
loads the same application composition as the daemon, resolves the accepted
config, and provides `prepare(...).preview()` and `prepare(...).run()`.
Transient scratch invocations are planned and executed in the notebook when
their closures or interactive objects cannot be reconstructed reliably in
another process. Every durable effect still passes through the daemon, so the
notebook never becomes a second writer.

The lower-level `sc.connect()` transport client exposes exact managed
submission, delegated execution, event replay, and attention resolution for
operator and infrastructure code.

After execution, analysis records, parameter proposals, review decisions, and
candidate activation use the same daemon boundary. A notebook may calculate
with arbitrary local Python state, but `Analysis.save()`, proposal review, and
configuration changes are durable daemon commands rather than direct storage
writes.

If an executor disappears, its resources remain quarantined. The GUI or
`lab.resolve_attention(run_id, action)` can explicitly:

- `release` resources after external state has been reconciled;
- `requeue` the admitted run with a new executor generation; or
- `abort` it with a structured terminal outcome.

A restarted daemon immediately fences executors from the previous process
instead of trusting their remaining TTL.

## GUI and event stream

The daemon serves the bundled GUI and a versioned, typed HTTP API. The GUI
reads health, catalog, run detail, resource state, and bounded measurement
pages from that API.

Server-sent events expose the same durable, globally ordered event log used by
the replay endpoint. A reconnecting GUI resumes from an event cursor and then
refreshes canonical state; it does not maintain an offline cache or a second
source of truth.

## Storage ownership

Per-run filesystem locks and multi-writer repositories are deliberately
absent. A single process-owner lock prevents two daemons opening the same lab
instance; inside that boundary, SQLite transactions and fencing tokens are
the only concurrency mechanisms.

The process-owner lock answers only “which daemon owns this lab instance?” It is
not a run coordination mechanism. Resource claims coordinate experiments,
executor leases coordinate delegated work, and SQLite transactions make
durable commits atomic.

The default transport is a same-user local control plane. It binds to loopback
and restricts accepted host names; it is not an authenticated remote service.
Remote or multi-user access needs a separate security boundary.

Each project has a `scopecat.toml` pointing at its version-controlled Python
application and optional bootstrap config:

```toml
[lab]
application = "my_lab.application:create_application"
bootstrap-config = "config/initial.json"
```

Start it with `uv run scopecat start ./my-lab`, then use
`uv run scopecat open ./my-lab` to open the GUI. The daemon selects an available
loopback port, publishes it in `.scopecat/daemon.json`, and stores durable state
below `my-lab/.scopecat`.

The bootstrap profile is imported only if the registry has no entries. After
that point the registry is authoritative: importing a file creates an immutable
entry, activation changes an explicit generation, and restart never silently
restores the bootstrap file. User code and seed/export files belong in Git;
runs, accepted snapshots, activation history, measurements, and artifacts
belong to the daemon.

| Owner | Contents |
|---|---|
| User project and Git | Python experiment/system code, `scopecat.toml`, editable split config inputs, and exported snapshots |
| Lab daemon | Run requests and manifests, execution events, measurements, analysis, proposals, immutable config entries, and activation history |
| GUI and notebooks | Views and commands against the daemon; transient scratch computation may remain in the notebook process |

Editing a Git-owned config file does not mutate the active registry entry.
Load the edited profile into a snapshot, import it through the Python client or
GUI, inspect the immutable entry, and then activate it with the current
generation. This explicit handoff keeps reproducible source files separate from
operator state.
