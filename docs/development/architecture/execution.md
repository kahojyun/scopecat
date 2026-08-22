# Experiment Execution Semantics

This document defines the cross-cutting contract between experiment authoring,
planning, domain compilation, and execution. Exact field and method behavior
belongs to the types that implement it; this document explains how those types
fit together.

## Program lifecycle

```text
@module / @experiment
    | close symbolic definitions
    v
program model           reusable graph, effects, products, and point plan
    | elaborate and verify without lab configuration
    v
VerifiedLogicalProgram
    | specialize against one accepted configuration snapshot
    v
BoundPlan               logical proof plus transient bound facts
    | materialize host effects and prepared target executions
    v
RunProgram              closed residual effect program
    | execute once through fenced effects and correlated job transitions
    v
logical measurements and durable run records
```

The authoring package owns Python UX. `scopecat.program` owns the reusable
symbolic model consumed by compilation. `BoundProgramFacts` belongs to one
specialization pass, and `RunProgram` is the executable form for one accepted
run. Physical batching preserves logical point, product, and result identity.

Check, preview, and run specialize the same accepted semantics. Check and
preview stop before provider effects; run interprets the closed effect program.

## Authoring ownership

A reusable module combines a pure typed graph with an ordered effect sequence.
Composing it scopes all resource, value, product, and effect identities to that
occurrence and places the effects once.

The public model has four boundaries:

1. `@module` defines a reusable fragment. Its Python return value is its
   composition result. `context.use(...)` places the occurrence and returns
   that typed result.
2. `@experiment` defines a complete invocation. `Input[T]` parameters become
   typed runtime values; ordinary Python parameters rebuild the structure.
3. A domain call is an ordered experiment effect. It returns products owned by
   that occurrence and may coexist with host-device work and derived-measurement
   compute.
4. The `@experiment` return value selects ordinary durable results. `Result(...)`
   annotations add stable identity, namespace, role, or metadata policy, while
   `alias(...)` handles the uncommon additional destination. These demanded
   roots determine the live compute and observation-stage graph.

A bare experiment uses its Python function name as its project-scoped technical
identity. An explicit `id=` distinguishes definitions when needed, while
`lab.run(..., name=...)` supplies the durable operator-facing name.

Every invocation resolves to one `PointPlan`: a grid or ordered point cloud,
plus repeat and traversal policy. Invocation edits replace or adjust that plan
without changing the experiment definition. An optional `AdaptiveDomainPlan`
pairs that initial prefix with a process-local domain optimizer and a hard point
limit.
The
[experiment dataflow model](../../concepts/experiment-dataflow.md#choose-and-edit-the-point-domain)
is the canonical task guide; the `PointPlan` docstring defines its exact local
contract. The durable admission records only optimizer identity and bounds; the
closure stays with the local runner. Static coordinates outside the adaptive
axis set partition the plan into stable regions with independent revisions,
observations, budgets, and stop state. A compact fragment proposal is normalized
into point candidates only at compilation; the whole group is accepted with
consecutive logical ordinals or rejected before effects. Measurement-dependent
selection across runs still belongs to a future workflow model.

### Local compute boundary

Python compute functions currently remain local closures owned by the runner
that planned the invocation. Preview reports a local diagnostic identity,
placement, and captured nonlocal names; none is a durable replay or remote
execution contract. Scopecat does not pickle closures or infer portability from
a function's module and qualified name, because either choice silently captures
environment and dependency state. Scientific dependencies should instead enter
the explicit typed input graph.

Completed-run analysis deliberately has a different authoring boundary. Inside
an analysis step, `context.trace(fn=fit, dataset=dataset)` eagerly runs ordinary
Python over the durable snapshot and optionally retains execution evidence. It
returns the native value; the author separately chooses whether to publish it
as a fact, dataset, table, figure, or artifact. If the published content exactly
matches the traced result's content and codec, a fact, dataset, or artifact is
linked to that execution automatically. A first-party native-dataset
normalization with field mapping instead records a typed derivation from that
result. Views remain explicit projections of a published dataset.

Every traced input is named and content-identified independently; JSON-safe
inline values are retained beside dataset targets. Analysis executions have no
experiment placement: they are not nodes in acquisition and do not mutate the
source measurement dataset. Full-dataset ordinary Python is the current
analysis path. A future streaming workflow may reuse publication and execution
evidence, but must own its cursors, checkpoints, and finalization state
explicitly.

Logical resource ports describe the interfaces and entities required by a
reusable definition. The accepted configuration maps those requirements onto a
finite catalog of physical endpoints. This keeps experiment definitions
independent of instrument names and channels while making every physical
selection deterministic and reviewable.

Product declaration, production, and durable selection remain distinct:

1. A module or domain call declares product identity, type, and shape.
2. An acquisition or domain execution produces those products at an exact
   effect position.
3. The experiment return structure chooses which products and values become
   dataset records; explicit recording only refines that policy.

## Specialization and lowering

Point composition remains symbolic through verification. Specialization binds
accepted inputs and configuration values, applies point-plan edits and parameter
overlays, folds pure computation, removes undemanded work, and leaves a residual
host/domain program. External reads, writes, acquisitions, and invocations occur
only while interpreting `RunProgram`.

Linking preserves one canonical random-access logical point sequence without
eagerly constructing generated rows. Range and center/span axes retain their
compact sources; explicit-value axes retain their authored values. Parameter
overlays, host lowering, entity selection, and domain projection evaluate the
selected ordinals for the current bounded coverage batch. The
[scalability benchmarks](../scalability.md) track the remaining point-count
costs; the stable semantic promise is that physical partitioning does not change
logical point identity or results.

One `ExperimentSystem` owns one domain compiler. The compiler may internally
route supported dialects or invoke a lower-level target compiler after resolving
inputs. Planning interacts with it through one `compile_batch` boundary and
receives prepared executions containing the closed target artifact, exact
point/product mapping, physical authority, and target job invocation.

Planning asks the domain compiler for a small initial candidate maximum before
any point-local inputs are resolved. For each candidate, the compiler inspects
the complete request and returns the length of its largest compatible prefix;
core may shorten that prefix to align host-state regions or another domain call,
then calls `compile_batch` with the exact final points. Every prepared execution
reports the maximum candidate point count for the following window. The
compiler may derive compatibility and continuation feedback from aggregate
payload bytes, channels, samples, shots, device entries, or another target-owned
limit. Core still schedules contiguous logical points and uses the minimum
prefix or feedback when a window contains multiple domain jobs. This keeps
launch preparation bounded without forcing a target to reserve one worst-case
resource unit for every point. A local-only run uses a small initial window and
bounded follow-up windows.

Each target batch is one bounded coverage window. Host lowering forms stable
regions inside the window from adjacent points with equal, statically known
desired state. It reconciles that state at a region anchor and suppresses an
identical anchor at the next window. A physical state change, invocation,
acquisition, or payload-backed write creates a point boundary. Pure host
computation creates no hardware boundary.

Consequential stages retain author order inside each bounded region. Coverage
windows execute in point order; there is no promise that one stage remains
contiguous across every physical batch in a scan. Hardware behavior that
requires cross-point adjacency belongs inside one domain execution contract,
while stable peripheral state may remain a host effect around each region.

Program inputs configure runtime semantics. Compiler inputs configure lowering.
Both resolve from the same accepted snapshot and point overlays before the
compiler is called.

## Physical authority and shared state

Admission claims the complete static instrument footprint before any prepared
batch exists. Domain compilers declare their exact instrument ids. Local target
preparation contributes every structurally compatible route candidate; later
point-local entity selection narrows actual operations but cannot expand
authority. A run may therefore lease an unused local candidate instead of
performing an O(total points) route scan before admission. Each claimed
instrument is leased once for the run and provisioned through one worker-owned
driver session. Host and domain stages may use different properties of the same
instrument in their declared region order.

The scheduler owns instrument-level exclusion. Routing retains more precise
interface, entity, channel, component, and property addresses as command and
provenance data. It does not turn those addresses into a hierarchical lease
system.

Each prepared domain execution declares:

- the instruments it may execute against;
- exact setup and realtime property write footprints;
- exact host-provided property values required before realtime execution; and
- properties whose previous state evidence it invalidates.

Planning rejects host and domain writers that claim the same property address.
Disjoint properties on one instrument are ordinary. Requirements are checked
against preceding host coverage and reconciled after setup immediately before
realtime execution. Invalidation removes knowledge without granting write
authority or asserting a replacement value.

Physical coupling is expressed where it is known. A device or lab adapter may
expand a named policy into concrete requirements and invalidations for coupled
properties. This lets a target invalidate a guard offset or crosstalk-sensitive
neighbor without claiming permission to choose its value. The core operates on
the resulting property addresses rather than a generic crosstalk graph.

A target authority is the realtime execution island. External signal-chain
devices such as LOs may remain ordinary host-controlled instruments. Lab
lowering can read their reviewed setpoints to derive signed IF values without
granting the target runtime permission to program them. Common experiments
reconcile stable LO state around a domain segment; specialized LO-sweep
experiments author the explicit host schedule.

Physical routing is a pure projection of the accepted snapshot. Point-local
entity selection may choose among its configured routes, while live
availability and provider failure never select a replacement route. Path-changing
devices such as switches and probers are explicit effects, so their state is
part of the reproducible plan.

## Completion, failure, and evidence

Execution validates typed transitions for each consequential external
invocation. A domain job starts with its deterministic execution key. A
synchronous target returns terminal receipt/result evidence directly. A target
backed by an external job may instead return a JSON-serializable checkpoint
containing the provider job identity, a strictly increasing revision, an opaque
resume token, and inspectable progress, then implement `resume` until it returns
a terminal result or negative receipt. Core rejects transitions that change the
execution key or job identity, or replay a stale revision.

For a daemon-backed execution, selected invocation, checkpoint, and terminal
outcomes form one durable transition ledger. A write-ahead invocation transition records
the complete `DomainInvocationIntent` together with its deterministic execution
identity before domain setup, state reconciliation, or provider `start` can
perform effects. Target intent, compiler and capability fingerprints, artifact
identity, and execution summary therefore remain available without consulting
the transient compiler object. Every valid checkpoint is then synchronously
committed under the current executor fence before core calls `resume`. Every
terminal receipt, including a synchronous target's receipt, is committed before
result realization or provider failure escapes the domain effect. Invocation
and terminal writes are each idempotent by run and execution key; checkpoint
writes also include the revision. The ledger requires invocation to be first
and rejects changed job, node, or point identity and any transition after
terminal state. Batched policy retains the same complete sequence with a bounded
loss window rather than a transaction at every boundary.

Low-cost synchronous targets may instead select `abnormal_only`. Their ordinary
completed calls leave no lifecycle rows: measurement coverage and the compact
terminal counts are the success evidence. A `not_executed` or `unknown` receipt
persists the complete invocation and terminal outcome together, while an
interruption without a receipt persists invocation-only state. A completed
receipt is also retained when host result realization fails afterward. A
checkpoint is never discarded: observing one first promotes that execution to
the complete ledger, commits the invocation and checkpoint before `resume`, and later retains
its terminal receipt.

If invocation persistence is unavailable, no domain setup or provider call
starts and the failure is known. If checkpoint persistence is unavailable, the
pending provider job is not advanced and the run becomes indeterminate. A
cancellation observed during the write likewise retains the checkpoint and
stops before the next transition. If terminal persistence is unavailable, the
observed receipt still determines provider certainty and realization does not
start, but the terminal summary marks its detail ledger incomplete rather than
claiming that the exact receipt became durable.

Under a policy that retains it, an invocation without a later transition means
setup or the provider call may have been interrupted; it does not prove that
`start` reached the provider. A
checkpoint proves the last observed state was pending, while a terminal
transition proves the provider outcome was known to the executor. These facts
survive loss before the run-level terminal commit, but none alone grants replay
authority.

The daemon folds those facts into one bounded current-state row per observed
execution: `invocation_unknown`, `pending`, or `terminal`. This is a diagnostic
projection rather than a recovery policy, so it has no `recoverable` flag and no
resume command. An empty projection means that no invocation became durable; it
may be the intentional result of successful `abnormal_only` jobs and does not
prove that the client-owned program contains no domain job. Safe
continuation still requires an exact program position, an owned instrument
session, a reconstructed measurement sink, and any result payload needed after
a terminal receipt.

The run-level `DomainExecutionEvidence` is only a compact terminal index: target
ids, transition policies, and aggregate attempt, checkpoint, receipt, and status
counts plus a `detail_complete` flag. The flag means every detail selected by
those policies became durable; it does not promise one ledger row per successful
attempt. The terminal model does not copy every intent, checkpoint, and receipt
into a second terminal JSON document. Detailed diagnosis pages the transition
ledger, and the current-state projection carries the complete invocation beside
the latest retained transition. Consequently a fully audited dense sweep grows
the ledger by job, while `abnormal_only` grows it by exceptional job and the run
terminal model remains bounded by target and policy diversity.

Notebook diagnostics use the run facade rather than the executor transport:
`run.domain_jobs(limit=..., before=...)` pages current projections and
`run.domain_job_transitions(limit=..., before=...)` pages the retained timeline.
These are read-only evidence surfaces; exposing them on `RunHandle` does not add
resume or replay authority.

These durable transitions make interrupted provider state inspectable after
executor or daemon loss, but do not by themselves authorize continuing the run.
Daemon restart fences the instrument session, process-local measurement writer,
and original effect program. Reattaching those three owners safely is separate
from storing a resume token or terminal receipt. Partial target results also
remain a later result partitioning change; synchronous targets still return
terminal evidence without emulating an asynchronous provider.

Outside that domain-job sequence, execution does not maintain a durable
transition ledger for normal per-effect progress. Measurement prefixes,
coverage checkpoints, hardware-unknown outcomes, and the terminal result remain
the recovery boundaries. Effects have three semantic outcomes:

- **completed**: validated evidence proves the effect completed;
- **rejected**: evidence proves the effect did not occur; and
- **unknown**: hardware may have changed without correlated completion.

Unknown effects stop dependent execution and are never silently retried. Stable
operation identities provide correlation and duplicate detection; they do not
authorize retrying an unknown write. A terminal domain receipt refines this
boundary with `completed`, `not_executed`, and `unknown`; its exact evidence
requirements live on `DomainExecutionReceipt`.

`experiment.on_success(...)` is an authored state transition after complete
point coverage. Instrument configuration then applies its success action and
collects terminal readback before release. Failure and known cancellation abort
the instrument and may apply its configured safe-state patch while it remains
commandable. The `InstrumentSpec` docstring owns the precise lifecycle order.

Operator cancellation is durable daemon control. Queued work can stop
immediately; executing work observes cancellation at effect, coverage, job
transition, and target-owned hardware-batch boundaries. It still cannot
interrupt a blocking provider call in the middle. Cancellation, terminal
commit, and resource quarantine are described in the
[lab daemon model](daemon.md).

Instrument state snapshots, measurement prefixes, point-plan decisions, and
terminal outcomes are durable run evidence. Individual normal hardware calls
remain typed execution details. Physical values become dataset columns only
when the experiment explicitly records a scientifically meaningful value.
Output enable, for example, is ordinary requested state and may itself be varied
by an experiment.

Host acquisitions and domain executions feed one logical measurement stream.
Every physical result maps completely to logical points and product-use
identities before entering that stream. The terminal outcome and any explicit
hardware-unknown evidence are the source of truth for operator reconciliation.

## Semantic invariants

- A run uses one accepted request and identifiable configuration snapshot.
- Logical point identity and coordinates are independent of physical batching.
- Host and domain placement observe the same inputs and parameter overlays.
- Pure computation may be folded, shared, or hoisted without changing its value
  or its host-versus-observation availability semantics.
- Consequential effect stages retain their declared order inside each bounded
  coverage region.
- Stable state may reconcile once per region; observable or varying effects
  remain boundaries.
- Legal lowering and physical partitioning produce the same demanded products.
- Every physical selection is deterministic and retained in provenance.
- Every physical result maps unambiguously to logical point and product-use
  identities.
- Prepared target write authority is exact and does not expand from read-only
  dependencies or invalidations.
- External effects require current fenced executor authority.
- Unknown hardware effects are never silently retried.
- Provider failure never triggers implicit route failover.
- Abort, disconnection, quarantine, and terminal outcome remain explicit.

Tests should assert these laws rather than transient compiler fields, cache
behavior, or incidental batch counts.
