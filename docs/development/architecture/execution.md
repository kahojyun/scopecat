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
    | execute once with durable effect evidence
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
without changing the experiment definition. An optional `AdaptivePointPlan`
pairs that initial prefix with a process-local optimizer and a hard point limit.
The
[experiment dataflow model](../../concepts/experiment-dataflow.md#choose-and-edit-the-point-domain)
is the canonical task guide; the `PointPlan` docstring defines its exact local
contract. The durable admission records only optimizer identity and bounds; the
closure stays with the local runner. Each accepted candidate extends canonical
logical identity by one ordinal, while rejected proposals remain in the ordered
ledger and never reach effects. Measurement-dependent selection across runs
still belongs to a future workflow model.

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

Linking materializes one canonical ordered point sequence. Parameter overlays
and the durable point catalog consume those rows eagerly. Host lowering, entity
selection, and domain projection consume the same canonical rows only for the
current bounded coverage batch. The current eager point representation is
tracked by the
[scalability benchmarks](../scalability.md); its stable semantic promise
is that physical partitioning does not change logical point identity or results.

One `ExperimentSystem` owns one domain compiler. The compiler may internally
route supported dialects or invoke a lower-level target compiler after resolving
inputs. Planning interacts with it through one `compile_batch` boundary and
receives prepared executions containing the closed target artifact, exact
point/product mapping, physical authority, and runtime invocation.

Planning asks the domain compiler for a small initial window before any concrete
artifact exists. Every prepared execution then reports a maximum point count
for the following window. The compiler may derive that feedback from aggregate
payload bytes, channels, samples, shots, device entries, or another target-owned
limit; core still schedules contiguous logical points and uses the minimum
feedback when a window contains multiple domain jobs. This keeps launch
preparation bounded while allowing concrete artifact shape to control later
batches. A local-only run uses a small initial window and bounded follow-up
windows.

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

Execution records intent before each consequential external invocation.
Effects have three semantic outcomes:

- **completed**: validated evidence proves the effect completed;
- **rejected**: evidence proves the effect did not occur; and
- **unknown**: hardware may have changed without correlated completion.

Unknown effects stop dependent execution and are never silently retried. Stable
operation identities provide correlation and duplicate detection; they do not
authorize retrying an unknown write. A synchronous domain receipt refines this
boundary with `completed`, `not_executed`, and `unknown`; its exact evidence
requirements live on `DomainExecutionReceipt`.

`experiment.on_success(...)` is an authored state transition after complete
point coverage. Instrument configuration then applies its success action and
collects terminal readback before release. Failure and known cancellation abort
the instrument and may apply its configured safe-state patch while it remains
commandable. The `InstrumentSpec` docstring owns the precise lifecycle order.

Operator cancellation is durable daemon control. Queued work can stop
immediately; executing work observes cancellation at effect and coverage
boundaries. The current synchronous domain ABI can stop before or after a target
call but cannot interrupt it in the middle. Cancellation, terminal commit, and
resource quarantine are described in the [lab daemon model](daemon.md).

Instrument state snapshots, command intents, and receipts are durable run
evidence. They become dataset columns only when the experiment explicitly
records a scientifically meaningful value. Output enable, for example, is
ordinary requested state and may itself be varied by an experiment.

Host acquisitions and domain executions feed one logical measurement stream.
Every physical result maps completely to logical points and product-use
identities before entering that stream. Durable evidence is the source of truth
for final run status and operator reconciliation.

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
- Intent is durable before consequential invocation.
- Unknown hardware effects are never silently retried.
- Provider failure never triggers implicit route failover.
- Abort, disconnection, quarantine, and terminal outcome remain explicit.

Tests should assert these laws rather than transient compiler fields, cache
behavior, or incidental batch counts.
