# Lab Daemon

Scopecat has one durable writer per lab instance: a long-running local daemon.
GUI and Python processes are clients, even when Python executes an experiment
itself.

```text
GUI ─────────────────┐
                     ├─ HTTP + SSE ─ daemon ─ SQLite + object store
notebook client ─────┘                    │
  └─ client executor ──── fenced compute/results
                         └─ hardware batches ─┘
```

The daemon owns admission, run state, resource claims, executor leases,
configuration activation, event ordering, and every durable write. SQLite
transactions provide concurrency control inside that boundary. Content bytes
remain in an immutable SHA-256 object store so large values do not inflate the
control database. Clients never open either store.

`ControlRun` is the durable lifecycle authority:
`queued`, `leased`, `attention_required`, or `closed`. `RunManifest` keeps the
accepted snapshot, content index, and optional terminal outcome; it does not
duplicate scheduler state. Run list and detail queries read both in one SQLite
snapshot.

## Execution boundary

The notebook keeps its transient `RunProgram` and Python closures, while the
daemon admits the plan, hosts process-long instrument actors, and persists
execution results. Hardware effects cross the boundary as ordered batches. The
daemon acquires an owner epoch, freshly observes hardware, reconciles desired
state against that baseline, executes driver calls, deduplicates whole batches,
records concise command and receipt evidence, and owns abort-on-failure,
terminal readback, and connection retirement. Admission binds the expected
provider and instrument-description fingerprint; provisioning verifies that
contract before the first write. Renewable executor leases carry a unique
fencing identity, so an expired client cannot continue writing.

Admission and resource claims are durable before hardware access. The executor
atomically acquires its control lease; all later journal, measurement, and
terminal commands carry the lease identity. A measurement executor may also
read durable append identities to reconcile an ambiguous append response.
Lease validation, the effect receipt, and its durable event commit in one
SQLite transaction. Heartbeats update only the executor lease deadline; the
run's resource claims refer to their owner instead of copying token or expiry
state. Heartbeats do not append project timeline events. Lease grant, loss,
and resource quarantine remain durable state-change events.

The executor does not publish a second, process-local observation stream.
Run and event views refresh from replayable project SSE; each initial
connection or reconnection refreshes canonical queries to recover missed
changes. The separate health poll is only a reachability signal.

Each admission carries one flat set of target and instrument claims closed by
planning from the complete run program. The executor validates or acquires that
set once and holds it across provider provisioning and all coverage blocks;
there are no nested block leases or channel/group scheduler claims.

`sc.open_project(...).connect()` returns the normal notebook `LabClient`. It
loads the same application composition as the daemon, resolves the accepted
config, and provides `prepare(...).preview()` and `prepare(...).run()`.
Transient scratch invocations are planned and executed in the notebook when
their closures or interactive objects cannot be reconstructed reliably in
another process. Every durable effect still passes through the daemon, so the
notebook never becomes a second writer.

The same project client exposes event replay and attention resolution through
`lab.control`. Execution remains an internal implementation of
`lab.prepare(...).run()`, so notebook code has one connection entry point and
one owner for the HTTP transport.

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

If an executor disappears, its resources remain quarantined. After reconciling
external state, the GUI or `lab.control.resolve_attention(run_id)` atomically
publishes an indeterminate failed outcome, closes the run, and releases its
resources. The run cannot be resumed or requeued safely because the execution
program has no general replay contract. Submit a new run to execute again.

A restarted daemon immediately fences executors from the previous process
instead of trusting their remaining TTL.

## GUI and event stream

The daemon serves the bundled GUI and a versioned, typed HTTP API. The GUI
reads health, run detail, resource state, and bounded measurement pages from
that API.

Server-sent events expose the same durable, globally ordered event log used by
the replay endpoint. A reconnecting GUI resumes from an event cursor and then
refreshes canonical state; it does not maintain an offline cache or a second
source of truth.

## Storage ownership

A single process-owner lock prevents two daemons opening the same lab instance.
Inside that boundary, SQLite transactions and fencing tokens coordinate all
durable executor effects. Interactive instrument drivers already run inside
the daemon and use explicit daemon-owned sessions instead of a second lease.

The process-owner lock answers only “which daemon owns this lab instance?” It is
not a run coordination mechanism. Resource claims coordinate experiments and
direct sessions, executor leases fence external run execution, and SQLite
transactions make durable commits atomic.

The default transport is a same-user local control plane. It binds to loopback
and restricts accepted host names; it is not an authenticated remote service.
Remote or multi-user access needs a separate security boundary.

Each project has a `scopecat.toml` pointing at its version-controlled Python
application:

```toml
[lab]
application = "my_lab.application:create_application"
```

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
| User project and Git | Python experiment/system/config code, `scopecat.toml`, and exported complete snapshots |
| Lab daemon | Run requests and manifests, execution events, measurements, analysis, proposals, immutable config entries, and activation history |
| GUI and notebooks | Views and commands against the daemon; transient scratch computation may remain in the notebook process |

Editing Git-owned Python config code does not mutate the active registry entry.
The daemon does not watch, hot-reload, or rewrite that source; publishing a
changed snapshot is an explicit CLI or notebook action. This keeps reproducible
source separate from operator state and prevents an edit from silently changing
later runs. The repository and server READMEs own the corresponding commands.
