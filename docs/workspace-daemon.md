# Workspace Daemon

Scopecat has one durable writer per workspace: a long-running local daemon.
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
  definition supplies the process-local catalog and `ExperimentSystem`.
  `DaemonDefinition.active_config` or CLI `--config-profile` supplies the
  active configuration snapshot.
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

`sc.connect()` returns the synchronous notebook client. Its
`submit_managed(...)` method selects an exact catalog `(id, version)`.
`execute_delegated(...)` accepts an already planned run. The convenience
`run_scratch(invocation, config=..., system=...)` prepares, plans, and executes
notebook code locally, while routing every durable effect through the daemon.
Scratch execution therefore preserves interactive Python state without making
the notebook a second workspace writer.

If an executor disappears, its resources remain quarantined. The GUI or
`workspace.resolve_attention(run_id, action)` can explicitly:

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
absent. A single process-owner lock prevents two daemons opening the same
workspace; inside that boundary, SQLite transactions and fencing tokens are
the only concurrency mechanisms.

The process-owner lock answers only “which daemon owns this workspace?” It is
not a run coordination mechanism. Resource claims coordinate experiments,
executor leases coordinate delegated work, and SQLite transactions make
durable commits atomic.

The default transport is a same-user local control plane. It binds to loopback
and restricts accepted host names; it is not an authenticated remote service.
Remote or multi-user access needs a separate security boundary.

Start the default local daemon with:

```sh
uv run scopecatd --workspace ./my-workspace
```

It listens on <http://127.0.0.1:8765> and stores state below
`my-workspace/.scopecat`. Add
`--definition importable.module:callable` for managed registrations and their
hardware system, plus `--config-profile ./config-profile.json` unless the
definition returns `active_config`. Startup validates, content-addresses,
registers, and activates that snapshot idempotently.
