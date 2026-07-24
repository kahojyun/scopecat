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

The same project client exposes exact managed submission, event replay, and
attention resolution through `lab.control`. Delegated execution remains an
internal implementation of `lab.prepare(...).run()`, so notebook code has one
connection entry point and one owner for the HTTP transport.

After execution, analysis records, parameter proposals, acceptance decisions,
and default changes use the same daemon boundary. A notebook may calculate
with arbitrary local Python state, but `Analysis.save()`,
`lab.config.accept(...)`, and `lab.config.set_default(...)` cross into durable
daemon commands rather than writing storage directly. Acceptance authority may
be a person or a named, versioned automatic policy.

A candidate may be used for one run without changing the default. That run
records the producing run, analysis records, proposal ids, base config hash,
and resolved candidate hash. Verification is optional evidence: acceptance may
happen before it, after it, or without a dedicated verification run.

If an executor disappears, its resources remain quarantined. The GUI or
`lab.control.resolve_attention(run_id, action)` can explicitly:

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
application:

```toml
[lab]
application = "my_lab.application:create_application"
```

Start it with `uv run scopecat start ./my-lab`, then use
`uv run scopecat open ./my-lab` to open the GUI. The daemon selects an available
loopback port, publishes it in `.scopecat/daemon.json`, and stores durable state
below `my-lab/.scopecat`.

The application may lazily construct an initial `ConfigProfileSnapshot` with
Python. The daemon resolves and imports it only if the registry has no entries;
ordinary notebook connections do not read bootstrap inputs. After that point
the registry is authoritative: importing another snapshot creates an immutable
entry, activation changes an explicit generation, and restart never silently
restores the application seed. User code and editable config inputs belong in
Git; runs, accepted snapshots, activation history, measurements, and artifacts
belong to the daemon.

| Owner | Contents |
|---|---|
| User project and Git | Python experiment/system code, `scopecat.toml`, editable split config inputs, and exported snapshots |
| Lab daemon | Run requests and manifests, execution events, measurements, analysis, proposals, immutable config entries, and activation history |
| GUI and notebooks | Views and commands against the daemon; transient scratch computation may remain in the notebook process |

Editing a Git-owned config file does not mutate the active registry entry.
Use `scopecat config diff` to freshly evaluate that source and compare it with
the daemon default, then `scopecat config apply` to validate it, save an
immutable revision, and atomically move the default. Notebook code can express
the same intent with `lab.config.set_default(snapshot)`. This keeps
reproducible source files separate from operator state without requiring
ordinary code to manage entry ids or generations.

The daemon deliberately does not watch or hot-reload project Python. Executing
changed source is an explicit CLI or notebook action, so an accidental edit
cannot silently change later runs. `scopecat config export --output PATH`
writes the complete active snapshot for review or backup; the generated JSON
is not the primary authoring format.

For an operator adjustment, the GUI can instead derive typed scalar and table
operations from the active entry, ask the daemon to preview and validate the
complete candidate, and set the valid result as the default. It does not
rewrite the Git-owned source. A runtime-derived default therefore points the
operator to `scopecat config diff`; the browser cannot reliably infer whether
the Python source has since been updated. Once an adjustment becomes the
intended project default, make the equivalent source change and apply it.

The explicit import, registration, activation, rollback, and expected-generation
commands remain available for diagnostics and operator workflows. They are the
mechanism beneath the intent-oriented API, not required ceremony for routine
single-user experiments.
