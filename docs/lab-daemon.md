# Lab Daemon

This document describes the current daemon architecture. It is not a product
requirement or roadmap. Ownership, persistence, and process boundaries may be
evolved when that better serves the adoption and growth paths in the
[project charter](project-charter.md).

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
execution results. A backend endpoint owns raw drivers behind opaque connection
handles, keeping provider and driver details out of actors and services.
The daemon projects accepted configuration to per-device bindings before
calling that endpoint; worker providers cannot inspect topology, parameters,
routing, or run-start policy.
Hardware effects cross the boundary as ordered batches. The daemon acquires an
owner epoch, freshly observes hardware, reconciles desired state against that
baseline, validates and lowers complete commands to the driver backend ABI,
deduplicates whole batches, records concise command and receipt evidence, and
owns abort-on-failure, terminal readback, and connection retirement. Lowering
finishes before a batch is recorded as started; driver requests contain no run,
point, product, retry identity, or public payload transport body. Opaque payload
bytes are carried separately from their worker-wire JSON descriptors, then
decoded inside the worker before entering the driver API. Admission binds the
expected provider and instrument-description fingerprint;
provisioning verifies that contract before the first write. Renewable executor
leases carry a unique fencing identity, so an expired client cannot continue
writing. Collection arrays cross the same process boundary in the other
direction as hash-checked binary attachments; the bounded control response
contains only their typed descriptors and the rest of the receipt.

Admission and resource claims are durable before hardware access. The executor
atomically acquires its control lease; all later journal, measurement, and
terminal commands carry the lease identity. A measurement executor may also
read durable append identities to reconcile an ambiguous append response.
Lease validation, the effect receipt, and its durable event commit in one
SQLite transaction. Heartbeats renew the executor lease deadline and return
any durable cancellation request; the run's resource claims refer to their
owner instead of copying token or expiry state. Routine heartbeats do not append
project timeline events. Cancellation requests, lease grant and loss, and
resource quarantine remain durable state-change events.

The executor does not publish a second, process-local observation stream.
Run and event views refresh from replayable project SSE; each initial
connection or reconnection refreshes canonical queries to recover missed
changes. The separate health poll is only a reachability signal.

Each admission carries one flat set of instrument claims closed by planning
from the complete run program. A domain target remains an authorized composite
configuration identity. Each prepared target batch declares its exact physical
instrument footprint; planning unions those footprints, checks that they stay
inside the configured target authority, and gives only that set to the
scheduler. The executor validates or acquires it once
and holds it across provider provisioning and all coverage blocks; there are no
nested block leases or channel/group scheduler claims.
Domain runtimes execute device programs through that provisioned run host, so a
target and an ad hoc operation aimed at the same AWG share the same exclusivity
key and worker-owned driver instance.

The run host accepts generic device-scoped value ids rather than dataset product
ids. A target therefore receives raw worker acquisitions and owns the mapping,
DSP placement, and result realization needed by its domain artifact. Semantic
acquisition intent remains target IR; the target may lower it to raw capture
with target-side processing or a typed onboard-DSP acquisition when the
daemon-resolved driver contract supports that representation. Lab policy—not
the driver contract—chooses whether to require, prefer, or avoid onboard DSP;
the selected physical representation and versioned semantic convention are
retained in the immutable artifact. A device lowering is valid only when its
driver implements that convention; the reference lab runs the target and
device placements against identical traces as a placement conformance test,
while literal golden vectors independently fix signed-IF phase, sample-center,
window, and normalization semantics.
Multi-device target
execution uses explicit `prepare`, `load`, `arm`, one timing-domain `trigger`,
and `fetch` batches; ordering is visible and auditable even though the current
host executes each batch's device actions sequentially rather than promising
cross-device atomicity. Targets that require a shared edge may add a scoped
trigger epoch: the reference target names the execution position and expected
armed participants, then resolves either `fire_only` or `session_idempotent`
from lab policy and the timing-driver contract. Session idempotence permits
deduplication only while the same device/driver session retains its epoch
cache; it is not a durable recovery promise. An unknown receipt after reconnect
or process restart remains indeterminate instead of firing again.
Preparation is invocation-scoped: the target reasserts its required shared and
channel state after run-level provisioning and immediately before loading its
programs. Every prepare/load/arm/trigger/fetch operation is named by the domain
execution id. Retrying the same execution therefore replays the same daemon
operations, while two invocations of an identical artifact cannot collide in
the run-scoped receipt cache. Preparation is not silently hoisted across
invocations; a future optimizer would need an explicit state-preservation proof.
The domain runtime itself exposes one synchronous `execute` call. Scopecat does
not invent a provider job id, polling phase, or mid-call cancellation contract;
an asynchronous runtime can be added only when a real target supplies durable
job identity and recovery semantics.
Before those invocations are compiled, core presents the complete bounded
domain call to the domain compiler. The compiler returns ordered batch sizes
from its actual target constraints; core no longer slices solely from a global
point-count property. Ordinary scan results must be invariant to these batch
boundaries. A workflow whose points intentionally depend on retained device
state must model that sequence inside one domain program.

Each closed domain invocation also retains a target-authored execution summary
as journal evidence. This is a compact physical projection—instrument roles,
DSP placement, timing guarantee, and preparation scope in the reference
target—not an automatic dump of driver state and not a dataset variable. The
complete opaque target intent remains fingerprinted rather than copied into the
journal. The started transition owns that intent once; terminal transitions
refer to its fingerprint and add only compact receipt evidence. Ordinary run
lists remain quiet, while one run's detail view projects these entries as typed
`domain_executions` for provenance inspection.

Observed, baseline, and final instrument snapshots are durable run evidence,
not measurement variables. Their manifest entry exposes only a neutral summary:
property-change counts, changed instrument ids, and missing final readbacks.
Intentional transitions such as scanning output enable are therefore visible
without being mislabeled as validation failures; full snapshots are read only
when diagnosis or provenance needs them.

`sc.open_project(...).connect()` returns the normal notebook `LabClient`. It
loads only the application's planning composition, resolves the accepted
config, and asks the daemon for the serializable instrument-contract catalog
bound to that exact snapshot. Concrete providers, transports, codecs, and
drivers are constructed once in a spawned project instrument worker and never
enter the notebook process. The daemon control plane retains only serializable
catalogs and opaque connection handles. Transient client-planned invocations
are planned and executed in the notebook when their closures or interactive
objects cannot be reconstructed reliably in another process. Every durable
effect still passes through the daemon, so the notebook never becomes a second
writer.

The same project client exposes event replay, `lab.control.cancel(run_id)`, and
attention resolution through `lab.control`. Execution remains an internal
implementation of `lab.run(...)`, so notebook code has one connection entry
point and one owner for the HTTP transport.

After execution, analysis records, parameter proposals, acceptance decisions,
and default changes use the same daemon boundary. A notebook may calculate
with arbitrary local Python state, but `Analysis.save()`,
`lab.config.accept(...)`, and `lab.config.set_default(...)` cross into durable
daemon commands rather than writing storage directly. Acceptance authority may
be a person or a named, versioned automatic policy.
Physical device removal and rekeying use
`lab.config.migrate_instrument_inventory(...)`, a separate command that must
declare the destructive diff and is rejected until the affected domains are
drained.

A candidate may be used for one run without changing the default. That run
records the producing run, analysis records, proposal ids, base config hash,
and resolved candidate hash. Verification is optional evidence: acceptance may
happen before it, after it, or without a dedicated verification run.

Cancelling queued work commits a known `cancelled` outcome immediately.
Cancelling a leased run persists an idempotent request; the next executor
heartbeat exposes it, and execution stops at the next operation, hardware-batch,
coverage, or normal-completion boundary. An already-running hardware batch or
domain call is not interrupted in the middle. Provisioned hardware then uses
the normal failure finalization path before committing `cancelled`; if that
cleanup has an unknown outcome, the terminal result remains cancelled but its
certainty is indeterminate and the affected resources remain quarantined.

Cancellation and terminal commit are ordered by the same SQLite writer. If the
terminal commit wins, a later cancel returns `not_accepted` and does not rewrite
history. If the request wins, a pending successful terminal intent becomes a
known cancelled outcome and the client observes `RunCancelled`; a real failed
or indeterminate intent still wins over cancellation. At this last boundary the
effects and successful hardware finalization may already be complete, so the
cancelled outcome does not claim that earlier work was interrupted.

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

## Scalability boundary

The single daemon, SQLite writer, and local object store form the current
single-lab durability and ordering boundary. Large content remains in binary
objects; execution commits evidence at batch or checkpoint granularity; and
interactive queries and events use bounded pages, selections, and summaries.
The [scalability benchmarks](scalability-benchmarks.md) measure this boundary.

## Storage ownership

A single process-owner lock prevents two daemons opening the same lab instance.
Inside that boundary, SQLite transactions and fencing tokens coordinate all
durable executor effects. Interactive and experiment instrument calls share
daemon-owned sessions, while concrete drivers live in one project instrument
worker.

The process-owner lock answers only “which daemon owns this lab instance?” It is
not a run coordination mechanism. Resource claims coordinate experiments and
direct sessions, renewable ownership leases reclaim abandoned clients, executor
tokens fence external run execution, and SQLite transactions make durable
commits atomic.

The default transport is a same-user local control plane. It binds to loopback
and restricts accepted host names; it is not an authenticated remote service.
Remote or multi-user access needs a separate security boundary.

Each project has a `scopecat.toml` pointing separately at its version-controlled
control-plane application and worker backend:

```toml
[lab]
application = "my_lab.application:create_application"
instrument_backend = "my_lab.backend:create_backend"
```

The application may lazily construct an initial `ConfigProfileSnapshot` with
Python. The daemon loads the application at startup but invokes its bootstrap
factory only if the registry has no entries; ordinary notebook connections do
not read bootstrap inputs. After that point the registry is authoritative:
importing another snapshot creates an immutable entry, activation changes an
explicit generation, and restart never silently restores the application seed.
User code and editable config inputs belong in Git; runs, accepted snapshots,
activation history, measurements, and artifacts belong to the daemon.

The backend entry is imported only by the instrument worker. The daemon sees
its serializable catalog and opaque handles, not provider, transport, codec, or
driver objects.

| Owner | Contents |
|---|---|
| User project and Git | Python experiment/system/config code, `scopecat.toml`, and exported complete snapshots |
| Lab daemon | Run requests and manifests, execution events, measurements, analysis, proposals, immutable config entries, and activation history |
| GUI and notebooks | Views and commands against the daemon; transient client-planned computation may remain in the notebook process |

Editing Git-owned Python config code does not mutate the active registry entry.
The daemon does not watch, hot-reload, or rewrite that source; publishing a
changed snapshot is an explicit CLI or notebook action. This keeps reproducible
source separate from operator state and prevents an edit from silently changing
later runs. The repository and server READMEs own the corresponding commands.
