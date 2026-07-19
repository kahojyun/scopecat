# Experiment Compilation and Execution Target

This document defines the target compilation and execution model for Scopecat
experiments. It is both the direction-setting contract and the status record
for the execution-model migration.

The existing engine's stages, batching choices, cache behavior, intermediate
representations, and artifact shapes are not compatibility requirements. The
migration should make breaking changes directly and update affected code and
tests in the same pass.

## Goals

The target model should:

- preserve experiment expressiveness while making execution semantics easier
  to inspect and reason about;
- keep point spaces symbolic until a target or the runtime needs concrete
  points;
- use partial evaluation as the normal way to specialize an experiment for a
  request, configuration snapshot, and target;
- let domain compilers lower the pure, bounded parts of parameter scans and
  point computations that they can represent efficiently;
- represent host work, domain jobs, effects, products, and result correlation
  in one executable program;
- make consequential effect ordering and uncertain outcomes explicit;
- avoid turning every compiler pass into another durable intermediate model;
  and
- keep the core domain-neutral without forcing domain runtimes into a universal
  hardware representation.

## Semantic Invariants

The new implementation must preserve these user-visible semantics:

- A run uses an accepted request and an identifiable configuration snapshot.
- Every logical point has a stable identity and coordinates independent of
  physical batching or target lowering.
- A parameter override at a logical point is visible consistently to host and
  domain computations at that point.
- Pure computations may be folded, hoisted, shared, or pushed down without
  changing their values.
- Consequential effects retain their declared ordering unless a compiler can
  prove that reordering is valid.
- A domain job cannot cross an effect barrier that may change one of its
  inputs, resources, or observable results.
- Every demanded product has one complete, unambiguous mapping from physical
  results back to logical points and product identities.
- The runtime records intent before a consequential external effect.
- An effect with an uncertain outcome is not silently retried.
- Abort and cleanup semantics remain explicit.

The following are deliberately not semantic invariants:

- the number or names of compiler passes;
- exact stage tuples or segment boundaries;
- physical job or batch counts;
- whether a point-invariant operation was hoisted;
- engine cache keys, hit counts, or status events;
- current internal artifact, fragment, or plan shapes; and
- current host-versus-domain placement when both placements are semantically
  valid.

## Target Architecture

The architecture has two long-lived compiler representations:

```text
authoring model
    | elaborate and type-check
    v
CoreProgram             typed and symbolic
    | bind, partially evaluate, and lower domains
    v
RunProgram              closed residual effect program
    | interpret with an effect journal
    v
run records and canonical logical results
```

Specialization may use temporary compiler data structures, but it must not
introduce another public or durable plan hierarchy. Compiler passes are
functions over these models, not proof wrappers that restate the whole
experiment.

### Implementation Status

The execution-model migration described here is implemented. `CoreProgram`
owns one ordered effect sequence, and `RunProgram` owns one single-use coverage
iterator interpreted without reconstructing host/domain lanes at runtime. A
closed expanded scan follows the same bounded admission, execution,
measurement, and persistence path for every experiment system.
Normal execution does not construct the former bound-plan, prepared-plan,
segment, lane, fusion, coverage-reconstruction, execution-cache, or
measurement-fragment models.

Point composition remains symbolic through verification and specialization.
The synchronous runtime may still close a static scan's complete logical point
catalog during `RunProgram` compilation because expanded axes normally fit in
memory. Execution does not depend on pre-registering that inventory: each
coverage block admits a contiguous `RunPoint` range into an append-only ledger,
closes and records that block's measurements, and releases its candidates before
requesting the next block. Domain compilers receive one request per exact
coverage block, so input binding and partitioning cannot cross later blocks.
They also receive complete specialized program inputs, supported point-axis normal forms, and
a budgeted selective-input resolution API. The resolver closes literals and
affine finite axes directly, then makes at most one binder call for the remaining
inputs and returns one columnar batch instead of allocating per-point binding
wrappers. The internal verified point-domain AST is no longer part of the SDK
request. `DomainCompilation` records only the compiler's input and result-transform
absorption claims; residual sets are their canonical complements and are derived
at the preparation boundary rather than stored as a parallel partition. Parameter scans
participate through their effective typed point inputs after lexical overlay
resolution, while request- and configuration-static inputs may be absorbed
after core partial evaluation. Authoring scan or parameter-table models are not
leaked to the target compiler. Unsupported inputs and transforms remain
residual work. Selective resolution returns its concrete-binder provenance as
immutable data, and `DomainCompilation` closes that evidence. Its
concretely bound inputs must be a subset of the compilation's absorbed inputs;
the compile request carries no mutable binding history.

Physical domain batching is now represented only by canonical point ordinals
stored by `RunDomainJob`. Complete point
materialization closes only canonical
points and parameter bindings; it no longer evaluates every domain execution
input. After compilation, each job materializes only the input columns
not claimed as absorbed, while absorbed inputs remain exclusively in the target
artifact. The system's compiler receives one immutable compile request per
coverage block, which is
retained through point materialization because its normal forms and bounded binder
are exactly the selective input resolver reused by
preparation. The core bridge derives the selected compilation's input complement
and resolves it through that same API. Planning projects one SDK batch context
from the request, canonical points, and those residual columns. The
former
`DomainPlanProjection`, `MaterializedLinkedPointBatch`, and point-domain view
proof wrappers, followed by `MaterializedDomainExecution` and
`DomainBatchView`, have been deleted. `DomainBatchContext` owns one concrete
execution and its closed measurement catalog; point references and residual
transforms are derived from that execution instead of stored as parallel batch
fields. It no longer echoes compiler identity. Result correlation depends only
on the catalog and SDK run points rather than reaching back into a linked compiler
plan. Batch selection therefore no longer creates another compiler IR, identity
namespace, or durable ownership layer.

The core bridge now recognizes input expressions before the SDK boundary.
`DomainInput` carries only its port identity and an SDK-owned scalar
literal, point-affine normal form, or opaque marker. Its type lives once on the
corresponding program input port rather than being copied onto the residual.
Canonical Core scalar, series, and relation AST nodes are no longer exposed to
domain adapters. Exact finite literal axes are analyzed once by the verified
compiler and projected with compact ordinal repetition metadata into the SDK's
read-only `DomainIterationLayout`. The layout
preserves ordered product, positional zip, known leaf extents, exact axes inside
partially opaque grids, and opaque structural boundaries, so a target can
distinguish slow and fast factors without receiving the Core point-domain AST.
This allows a target to lower an
affine scan without binding its domain input or expanding a Cartesian product.
Finite `values`, `grid`, `linspace`, and range axes retain exact values and
strides. Dependent products preserve their left/right nesting even when the
inner value generator remains opaque, so targets can distinguish a dependent
boundary without receiving the Core relation AST. Unproven values still use
the bounded binder.
Integer arithmetic preserves
provable bounds through addition, subtraction, and multiplication, allowing a
non-negative affine expression to satisfy a constrained target port without
weakening its type. The Fake X, CZ-phase, and DRAG-beta compilers all use the
same resolver; their finite literal scans no longer invoke concrete domain-input
binding.

Result ownership is derived once from typed product-use edges, independently
of target lowering. That stable closure says which direct and derived results
belong to a domain call; compiler specialization then partitions its transforms
into target-absorbed and residual host work. This keeps correlation semantics
out of target policy and avoids treating every transform in the ownership
closure as if it had been pushed down.

Domain result correlation does not impose a target-entry model. Preparation
binds each opaque target result location directly to context-owned logical point
and product-use references, then validates exact logical output coverage. A
target adapter may internally derive those bindings from list entries,
segments, array indices, or another native inventory, but core retains none of
that physical hierarchy. One result location may fan out to multiple uses of
the same logical product; distinct locations cannot silently supply conflicting
values for that product.

Config-bound route and constraint data used during specialization is temporary
planning data, not compiler linking IR or an executable plan. Local
materialization and route constraint validation live at the planning boundary,
where they directly construct final execution operations. Provider ABI
description precedes host point materialization, so planning has the final
instrument order while constructing final point operations. Local
materialization produces only transient tuples of already-bound point
operations; the former executable-looking `LocalExecutionPlan`, its structural
program protocol, and the production `MaterializedPointEffects` wrapper have
been deleted. Blocking diagnostics raise `CheckFailed` at that boundary.
`RunHostBinding` contains provider provisioning data and resource order, but no
duplicate point or product inventory. System planning closes the small point
inventory and selects local implementations, product realizations, and
run-invariant compute exactly once. The single-use coverage iterator then materializes
parameters, lowers point effects, and invokes domain compilation for only its
current bounded ordinal range. Verified variation analysis derives support for
each state effect directly; only consecutive declarations in one desired-state
region are merged for conflict checking and coverage. Lowering retains the
ordered `CoreProgram.effects` slots instead of unioning state dependencies
across domain or action boundaries and reconstructing order from materialized
commands. Actions remain hard sequencing boundaries, and
`coverage_block_size` caps materialization rather than defining semantic state
barriers. Every bound local effect is emitted as one
`RunCoverageEffect` over its
exact logical coverage. Point computations use compiler-derived
`PointVariationSupport`; the interpreter evaluates them once per contiguous
coverage and seeds the result into those point frames. Stable state uses the
same coverage form, while actions and ordinary host collection remain singleton.
This is bounded compile-time common-subexpression elimination, not a runtime
memo cache. No stage batch or dynamically open point scope survives into
execution. Host-only, mixed, and domain-only
runs all complete and release exact logical coverage at explicit checkpoints
inside a bounded block. Mixed runs interleave domain jobs only at data, ordering,
or resource-conflict barriers; unrelated state changes do not fragment jobs.
Domain lowering writes
`RunDomainJob` operations with exact logical-point and product correlation.
The small scan-axis inventory closes before execution planning; domain input
normal forms remain symbolic, while parameter binding and effect lowering are
materialized by bounded ordinal blocks. `coverage_block_size` limits
point binding, domain barrier coverage, and residual execution blocks rather
than rejecting a scan because its total cardinality is larger than a global
budget. The final program retains a single-use coverage iterator, not a whole-run
tuple of lowered blocks. It has no second point-loop hierarchy or lazy expansion
adapter.
Resource ownership has two explicit lifetimes. Provider instruments are known
before coverage and held by the run lease. Point routes, channels, shared
groups, and domain target claims live on the exact `RunCoverageBlock` that uses
them and are leased only while that block executes. Coverage claims already
held by the run lease are removed, so nested acquisition does not repeat the
same resource. Host-backed and domain-only
programs enter one provisioning-and-interpretation function and return one
execution outcome containing setup diagnostics, logical domain candidates, and
any captured domain failure; the run boundary no longer maintains separate
host/no-host interpreter branches or parallel result side channels.
`DomainCompiledJob` is a lightweight one-shot artifact recipe plus exact point
coverage. The compiler declares its coverage-invariant target resource
footprint before artifact compilation, so planning forms legal state barriers
before calling `compile`; jobs do not repeat those claims. `RunProgram` does not retain a
materialized `PreparedDomainExecution`, target waveform bundle, or generic
artifact for every job. At the corresponding coverage block, the recipe is
materialized, `prepare` closes it into the invocation payload, and both the
recipe and rich `DomainBatchContext` are released. Only closed invocation,
output, transform, runtime, and point data live across that effect. Resource
claims are authoritative before compile time, so neither barrier construction
nor acquisition depends on materializing a heavyweight payload first.
Raw point rows, selected-product realization objects, and nested compute result
wrappers are discarded at the binding boundary instead of being mirrored into
another plan API. Resolved routes are likewise temporary: materialization
uses them to validate point-local constraints, bind final effect fields, and
close instrument/channel/group claims once. The former `BoundPoint` and
executable `PointProgram` models have been removed; local lowering emits exact
coverage effects directly, retaining point identity only in their ordinal
coverage. `ResourceClaim` is a shared
kernel identity rather than an execution-port-owned compiler dependency. Action
binding already emits final `InstrumentActionOperation` values; there is no
intermediate bound-action model or second action conversion pass. State binding
retains owner and logical-port metadata only in `PendingResourceState` while
checking point-local constraints, then immediately emits final
`ApplyStateOperation` values. Final point programs no longer carry or convert
bound-state wrappers. Product realization follows
the same rule: `PendingCollect` retains logical-port metadata only through
resource and duplicate-key validation, then planning constructs final
`CollectProductRequest`, `CollectionResultBinding`, and `CollectOperation`
values. The former bound collect/request/axis models and their execution-side
conversion pass have been removed. Compute binding also constructs final
`BoundInput`, `OutputInput`, `ComputeResultSlot`, `PayloadSlot`, and
`ComputeOperation` values directly. The former bound compute call/value/output
models and their conversion pass have been removed; planning writes the already
topologically ordered operations directly into the point operation sequence.
`RunProgram` no longer retains the compiler-owned `MaterializedLinkedPoints`
container. It owns a minimal `RunPointCatalog` with experiment identity,
logical point identities, coordinates, and coordinate order; preview and the
run interpreter consume that catalog without traversing back through
`LinkedPlan` or `CoreProgram`. Stable point-domain and logical-point identities
live in the dependency-light kernel rather than the typed compiler package.
Measurement value selection, record projection, and host-transform graphs now
share a closed `MeasurementValueCatalog` containing that run point catalog and
the final product inventory. None of those executable objects retains
`MaterializedLinkedPoints`; the sole compiler-aware measurement bridge projects
the catalog once at the planning boundary. Domain batches receive the same
closed catalog shape restricted to their logical points.
The complete `RunPointCatalog` is the accepted static inventory used by preview
and bounded source construction. It is intentionally distinct from the runtime
`AdmittedPointLedger`, which records only the contiguous prefix that actually
entered execution and therefore remains truthful after a failed run. The
measurement projection retains only the point contract, not another concrete
inventory. Runtime projection produces
a `ProjectedMeasurementDataset` for each admitted coverage. Successful
persistence appends it through a `MeasurementDatasetWriter`, returns the
committed records directly, and seals the aggregate at the run boundary;
receipts remain journal and repository evidence instead of becoming another
successful-result wrapper.
The former `local_semantics` module and `materialize_local_semantics*` API names
have also been removed: final local execution is produced by
`materialize_local_execution*`, while short-lived `PendingRoute` values live
only beside their planning constraint checks.
Mixed runs encode point prefixes, domain jobs, and point suffixes in program
order instead of invoking a separate region engine. Canonical measurement
candidates from both placements are closed once per coverage block.

Barrier regions are derived from typed state and action dependencies rather
than equality of materialized commands. Configuration specialization now
partially evaluates scalar, series, and table values across compute, route,
state, action, and domain-call inputs before placement. Closed relation
subgraphs become typed literal values, including static children of otherwise
point-varying plans; domain bridges consume those residual values and their
retained binding times instead of specializing privately. Scanned parameter
tables remain residual so their lexical point overrides cannot be frozen.
Known series and tables carry exact specialized bounds instead of retaining
their wider authored cardinality contracts.
Configuration linking and specialization own this partial evaluation and
sealing step. Experiment-system lowering consumes the resulting specialized
`LinkedPlan` directly. `ResolvedExperiment` remains the pre-link authoring
boundary because it intentionally permits physical resources that a later
configuration link may reject; the redundant `LinkedExperiment` pipeline
envelope has been removed.
The experiment system projects one static `DomainCompileTemplate` per domain
call from the specialized `LinkedPlan`. It closes the domain body, typed inputs,
normal forms, iteration layout, and result ownership once; each bounded
coverage binds only barrier regions and a selective input resolver before invoking the
compiler. A compiler can partition logical ordinals without resolving
inputs, or resolve a selected input set through one normal-form-first API. One
ordinary lowering boundary now owns capacity partitioning and invokes the
target artifact compiler once for each resulting barrier-contained partition.
When capacity permits, its default partitioner closes complete innermost sweeps
before splitting a slower factor; barriers remain authoritative and may clip a
sweep. The lowering boundary also supplies each artifact compiler with its
selected resolved columns and
aggregates binder provenance into the compilation result. Inputs requested for
artifact lowering are absorbed by construction, so adapters do not repeat the
same ids as a separate claim; explicit absorption remains available for
structure or literals that need no resolved column. Adapters no longer
construct a parallel partition list or maintain a side-channel binding ledger.
Finite point leaves in independent products, dependent products, and positional
zips expose exact column axes with compact ordinal repetition without invoking
that binder. A shared linking-layer materializer closes the small point-domain
inventory at most once. One verified `VariationAnalysis` derives parameter,
route, compute, and per-state support from canonical dependencies. Effective
parameter relations, resolved routes, compute coverage, and state barriers use
the same projection fact only within the current coverage; local lowering,
domain compilation, and domain preparation share the resulting bindings.
Selective domain-input columns use the same
coverage lifetime: repeated requests within the block reuse them, but no
scan-wide parameter or input cache survives after its jobs are prepared.
Exact-cardinality point spaces
now support ordinal-aware evaluation:
product ordinals are decomposed into factor ordinals, zip ordinals are pushed
to each source, and dependent right branches are evaluated only for selected
left rows. Relation leaves push ordinal selection through literal, parameter,
input, grid, projection, derived-column, and limit nodes; operations such as
filter, sort, and join that do not preserve stable input ordinals safely fall
back to complete evaluation. Specialization also rewrites point-space leaves,
removes empty-row unit leaves, converts dependent products whose right side no
longer observes the ambient point into ordinary products, and collapses known
empty compositions before their remaining factors reach point materialization.
The pure compute DAG is reduced to the transitive closure demanded by state and
action effects before implementation selection. Residual computations whose
transitive inputs contain no point column or route are bound once, written as
explicit `RunCompute` operations, and made available to every point evaluation
state rather than being copied into each iteration. Point scope is derived from
dependencies, not declared on the output or inferred from its payload type.
Point-varying computations retain content identity for payload provenance, but
their execution coverage comes from structural variation support rather than
recovering rate by comparing bound operations after the point loop.
This provides structural sharing across the point loop without a runtime cache.

### CoreProgram

`CoreProgram` is the canonical typed meaning of an authored experiment. It
contains:

- a symbolic `PointSpace` algebra, including singleton, row, product, zip, and
  dependent composition where supported;
- a typed value graph for constants, accepted inputs, configuration bindings,
  point fields, runtime results, and pure operations;
- an ordered effect graph for state application, actions, acquisition, domain
  calls, and other external operations;
- product definitions and demand edges; and
- source information for diagnostics and provenance.

A domain call is a normal typed effect node with value inputs and outputs. The
model permits multiple domain calls and does not divide an experiment into
exclusive host and domain lanes.

Configuration and parameter data use one immutable typed binding model.
Scalar, series, and table presentation forms may remain at the authoring and
record boundaries, but compiler semantics must not depend on mutable
point-local table copies.

### RunProgram

`RunProgram` is the only executable representation. It is a closed, typed,
structured program that may contain:

- residual loops over logical points;
- pure host computations;
- state changes and actions;
- domain jobs or job templates;
- acquisitions and result transforms;
- explicit sequencing and effect barriers;
- concrete resource claims; and
- exact logical-result correlation.

Values are connected by typed identities and dataflow edges. Inputs, products,
measurements, and fragments are not repeatedly re-described at every boundary.
One interpreter or scheduler executes the program; domain execution is an
operation in that program rather than a callback into a second engine mode.

## Partial Evaluation

Partial evaluation is part of compilation semantics, not an optional
optimization. It replaces eager point materialization, mutable point overlays,
late structural fusion, and runtime memoization of statically knowable work.

Pure relation specialization distinguishes only the binding times it can
actually resolve:

- request-static: accepted invocation inputs and capture-time constants;
- configuration-static: values from the accepted configuration snapshot;
- point-varying: values determined by a logical point or scan axis.

External-operation dependence, lexical row ownership, and residual compute
scope are separate structural facts. They are not collapsed into a global
stage/rate classification on every value.

Evaluation of a pure node produces either a known typed value or a residual
typed expression with explicit dependencies. Partial evaluation may:

- bind request and configuration values;
- fold pure operations and statically selected branches;
- substitute scanned parameter reads with point expressions;
- hoist point-invariant pure work;
- share equivalent pure subexpressions;
- remove undemanded computations and products;
- simplify point-space algebra; and
- expose a smaller residual subgraph to a domain compiler.

The current compiler performs configuration-static expression hoisting by
replacing closed scalar, series, table, and relation subgraphs with typed
literals before point binding. It also removes compute nodes outside the
effect-demand closure. Opaque operations and portable pure operations that
transitively depend on them form the residual compute graph. That graph is
partitioned into run and point scopes from its transitive input dependencies.

It must not execute live reads, state mutation, actions, acquisitions, or other
effects. It must also use explicit materialization budgets so that simplifying
a point space does not accidentally expand a large Cartesian product.

### Parameter Scans

A parameter scan is a lexical or SSA-style binding override over a point-space
region. Reads of that parameter within the region resolve to the point-varying
binding; unrelated reads can still become configuration-static values.

This rule applies before host-versus-domain placement. A host evaluator and a
domain compiler therefore receive the same effective parameter semantics
without copying or mutating a parameter table for every point.

## Domain Compilation

Domain compilation is a bounded lowering step inside specialization. A domain
compiler is pure: it does not submit work, inspect live state, or perform
external effects.

`DomainCompilation` contains lowering claims and locally scoped jobs; it does
not echo compiler or target identity. The system compiler may route different
domain calls to different physical targets. Its pre-compile resource footprint
is authoritative for planning; each prepared invocation closes the actual
downstream compiler and target for execution and provenance.

The core provides a domain compiler with:

- the typed domain body and ports;
- complete typed program inputs with SDK-owned normal forms or an opaque marker;
- a read-only SDK projection of the compiler-owned symbolic iteration layout,
  with product, zip, exact axes, partially known grid leaves, and opaque
  boundaries;
- exact logical ordinal barrier regions when cardinality is statically known;
- normal-form-first resolution for compiler-selected inputs, with one budgeted
  concrete fallback;
- demanded outputs;
- surrounding effect and resource barriers;
- an immutable target capability snapshot; and
- compilation policy and concrete capacity limits.

Within those inputs, a domain compiler may:

- bind domain-specific constants, calibration data, and program structure;
- absorb finite scan, product, and zip axes it can represent exactly;
- lower scan axes into target list, register, table, shot-loop, or equivalent
  constructs;
- fold and share domain computations;
- deduplicate programs, waveforms, or other target artifacts;
- prune undemanded outputs;
- push down explicitly portable pure result transforms;
- split physical jobs according to real target limits; and
- choose physical execution order when it returns an exact logical mapping.

The SDK layout can also partition a barrier by any selected set of exact axes.
The domain compiler may use those regions while compiling, but the SDK does not
prescribe a shared-artifact recipe or a second job factoring mechanism. Artifact
sharing is an ordinary target lowering decision inside `compile`.

A domain compiler must not:

- change logical point identities, coordinates, or parameter semantics;
- inspect or execute live reads, actions, receipts, or state mutations;
- cross an effect barrier whose state or resources affect the domain job;
- reorder observable effects without an explicit proof accepted by the core;
- evaluate opaque host Python; or
- claim an output for which it cannot provide complete correlation.

The lowering result replaces the accepted subgraph with `RunProgram`
operations and an exact logical-point/product mapping. Unsupported residual
work remains in the host program. The core validates point and output coverage,
mapping uniqueness, the predeclared resource footprint, and barrier containment.

Each experiment system provides at most one domain compiler. A system that supports
multiple dialects or physical targets owns explicit routing from dialect/version
and target capabilities inside that compiler; core does not probe competing
adapter plugins.

The notebook-facing `scopecat` facade does not re-export the domain adapter SDK.
Integrations import `scopecat.sdk.domain`, whose facade is a direct set of typed
contracts rather than a second lazy plugin registry. The compiler's `compile`
and `prepare` methods remain separate because pure target lowering and runtime
resource binding have different effect boundaries. `DomainPreparationBuilder`
is the single context-bound closure API for result mapping, measurement ownership,
invocation identity, and decoding; there are no per-hook plugin factories behind
it. The private core bridge projects verified compiler data into those contracts
and is not an adapter extension point.

### Fusion

Fusion is not part of the target model. It is replaced by symbolic point-space
specialization and domain lowering.

Physical batching is a domain compiler decision constrained by target
capabilities and effect barriers. A single-point policy is simply a lowering
limit such as `max_job_points = 1`; it is not a separate execution path. Tests
must compare logical results and safety invariants rather than exact batch
boundaries unless a target capability makes a boundary semantically relevant.

## Runtime and Effects

The runtime executes one `RunProgram`. It has one resource-ownership model, one
effect journal, and one terminal outcome derivation.

For each consequential effect, the runtime records an intent before invoking
the provider. The provider reports one of these semantic outcomes:

- completed, with a validated result or receipt;
- rejected, meaning the effect is known not to have occurred; or
- unknown, meaning the effect may have occurred.

An unknown outcome stops dependent execution and is never automatically
retried. This contract remains even if provider APIs use richer internal
states.

The initial target runtime is synchronous at the `RunProgram` boundary. A
future resumable job system must be introduced as an explicit run suspension
model rather than hidden behind a synchronous submit/fetch bridge.

The execution boundary admits points only when their bounded block is yielded.
The initial local runtime uses a synchronous, single-use iterator over a closed
scan; total point count comes only from the run point catalog. Explicit coverage
checkpoints commit and release completed measurement prefixes inside a larger
block. Measurement-guided admission is intentionally not part of this contract.

Runtime-local memoization is not a public execution semantic. Pure reuse is
handled through partial evaluation and common-subexpression sharing. A future
cross-run compiled-artifact cache belongs outside the interpreter and is keyed
by compiler, target, capability, and input digests.

## Results, Records, and Observability

Execution emits canonical logical measurements once. Physical chunks and job
results are correlated before they cross the run-record boundary. The run
manifest indexes the canonical content rather than reloading and rewriting the
same measurement through several fragment forms. Domain jobs emit the same
logical `MeasurementValueCandidate` stream as host collection; the interpreter
does not group candidates by a temporary compiler/source identity before value
assembly, because point and product-use identities already provide complete
correlation.

Measurement arrays remain ordinary in-memory values in the initial synchronous
runtime. Consumers may process and release them incrementally as coverage is
interpreted; the model does not yet define external array references, durable
object protocols, or engine-owned reference counting. Peak-memory optimization
can be added later without changing logical measurement identity or coverage.

Each successful append returns a small receipt. Terminal evidence and the run
manifest use ordered append digests and the seal digest without reloading or
retaining committed records. Repository reload is reserved for uncertain or
partial recording recovery; it is no longer part of the normal terminal path.

### Completed simplification checklist

- [x] Remove `ValueAvailability`, its declared plan/execute/result stages, and
  run/point/row rate lattice. Derive residual execution from semantic dataflow,
  row visibility from lexical ownership, and run-versus-point compute scope from
  transitive point and route dependencies.
- [x] Remove unused execution/result `BindingTime` variants and the dead binding
  time copied onto `ValueInput`; retain binding time only inside pure partial
  evaluation where it changes specialization.
- [x] Contract the domain runtime to one synchronous submit/fetch path with
  explicit success, rejection, or unknown outcome.
- [x] Emit local collection results directly into the same logical measurement
  candidate stream as domain results; do not reconstruct or reload a second
  value fragment after execution.
- [x] Retain one closed domain result mapping after validation instead of a
  parallel native/proof object hierarchy.
- [x] Give run-rate pure computation its own evaluation frame rather than
  manufacturing a synthetic logical point.
- [x] Collapse measurement selection, binding, projection, and committed-result
  wrappers into a planning projection and a canonical runtime batch.
- [x] Remove the compiler pipeline envelope that merely repeated a linked plan,
  request, and configuration source without establishing a new invariant.
- [x] Close domain results directly into one result mapping and one canonical
  measurement-candidate stream, removing source-output and proof wrappers.
- [x] Replace separate artifact, dataset, and record indexes with one
  content-addressed manifest index, and publish terminal content through one
  repository commit.
- [x] Retain one local lowering entry that accepts already-materialized linked
  points; point closure is owned by system planning and cannot recur inside local
  lowering.
- [x] Return provider setup, host effects, domain candidates, and domain failures
  in one `RunEffectResult` instead of an execution wrapper plus side channels.
- [x] Remove the speculative execution-recovery inspection API and require every
  indexed run content entry to carry a real content digest.
- [x] Bind run-rate compute exactly once and point-varying compute once per
  distinct structural variation coverage; evaluate state and
  action expressions in the same bounded point pass rather than building
  whole-run temporary record lists.
- [x] Express journaled state, action, and collection effects through one durable
  intent/invocation/outcome lifecycle while keeping their domain-specific
  commands and successful continuations explicit.
- [x] Return committed measurement records directly, retaining only concrete
  uncertain-write evidence on failure instead of exposing an unused
  attempt/retry/reconciliation protocol.
- [x] Implement artifact, dataset, and record lookup through one role-driven run
  content access core without removing the public role-specific convenience
  functions.
- [x] Keep consumer-context relation proof verification, but make the consumer
  table a diagnostic index over verified plans rather than another owner of
  value-expression proof envelopes.
- [x] Return only observed effect facts from the effect interpreter and derive
  terminal result, certainty, and termination reason once at the run boundary.
- [x] Keep concrete instrument providers outside `RunProgram`; inject them only
  at interpretation, and remove duplicated experiment, point, product, and
  configuration fields from the host binding.
- [x] Reduce local materialization output to point operations, resource order,
  claims, and run-rate compute instead of carrying compiler identity and product
  inventories into another planning envelope.
- [x] Keep provider description and host ABI validation in planning, retain only
  the resulting host binding in `RunProgram`, and pass the concrete provider to
  the outer runtime resource scope without threading derived program fields.
- [x] Derive compute totals from completed runtime transitions instead of
  copying observation statistics into executable operations or
  `RunEffectResult`.
- [x] Separate provider binding, compute lowering, typed value evaluation, and
  receipt validation by semantic ownership without introducing another plan or
  execution wrapper.
- [x] Remove the test-only local effect program and its obsolete product
  inventories; focused interpreter tests now consume materialized effects and
  explicit runtime metadata rather than requiring a production context shim.
- [x] Normalize transient payload wrappers through one kernel utility and keep
  content-identity tests on the real fingerprint contract instead of exporting
  a production test hook.
- [x] Commit every durable execution transition through one exact journal
  primitive while retaining caller-owned failure, interruption, and uncertainty
  policies for host, provider, domain, and measurement effects.
- [x] Keep concrete point grouping inside planning, flatten host-only and mixed
  runs into the same atomic effect/completion stream, and remove `PointProgram`,
  `RunPointLoop`, lazy operation expansion, and the interpreter's reconstructed
  empty point object.
- [x] Keep internal point instructions out of the package-level public API and
  inspect planning results through test-only operation queries instead of
  production flat-lane properties.
- [x] Remove the final compute/state/action/collect stage containers, write each
  local operation atomically into `RunProgram`, and bind routes and point effects
  in one local-materialization pass.
- [x] Separate lazily retained host point evaluation state from logical point
  completion, remove `RunPointStart` and `RunPointEnd`, and terminalize every
  point covered by a failed multi-point domain job without requiring open frames.
- [x] Bind opaque domain result locations directly to logical point/product-use
  references, removing generic target-entry inventories and entry-point
  bijection from the core domain ABI while retaining exact output closure.
- [x] Derive exact effect barriers from materialized state signatures and delete
  the symbolic singleton-barrier analyzer.
- [x] Invoke each residual host measurement transform once over canonical point
  columns, including the public domain bridge and reference quantum transforms.
- [x] Persist canonical records through contiguous append operations followed
  by one run-level seal; publish a known committed prefix on failed runs without
  reconstructing measurement fragments.
- [x] Replace point completion wrappers with exact coverage completion and carry
  `point_indices` through runtime observations and failure terminalization.
- [x] Preserve exact point spaces through domain compilation and materialize
  them in bounded ordinal blocks without rejecting larger total scans.
- [x] Derive domain measurement inventories from one result mapping and bind
  residual host transforms in one preparation step instead of copying source,
  derived, and complete product-use inventories into another plan.
- [x] Remove the unused measurement-transform rate axis and select host
  implementations directly by semantic contract instead of maintaining a
  separate binding registry.
- [x] Use dataset terminology consistently at the projection and persistence
  boundary: `ProjectedMeasurementDataset`, `MeasurementDatasetWriter`, and
  `MeasurementDatasetRepository`.
- [x] Replace flat point-effect/completion pairs with bounded
  `RunCoverageBlock` values whose exact coverage is completed once by the
  interpreter, and apply the materialization block limit to compiler barriers
  and residual execution blocks.
- [x] Remove `DomainMeasurementPlan`; derive result and product identities from
  one mapping and bind residual host transforms directly during preparation.
- [x] Remove production `MaterializedPointEffects`; keep the old point-shaped
  inspection view exclusively in test fixtures.
- [x] Keep the expanded scan-axis inventory in memory while materializing point
  parameters, local payloads, target artifacts, and prepared payloads only for
  the current coverage block.
- [x] Admit `RunPoint` values through one append-only run ledger at the coverage
  boundary instead of pre-seeding the interpreter with a complete point map.
- [x] Close, project, append, and release measurement candidates after each
  coverage block, then seal the admitted dataset at the terminal run boundary.
- [x] Make measurement value selection and its contract independent of the
  concrete point inventory; block closure consumes the actual admitted points.
- [x] Scope every domain compile request, selective input resolution, parameter
  binding, and compiler-controlled partition to the current coverage block.
- [x] Separate the run-level compute preamble from a single-use coverage
  iterator; expanded static scans are consumed without first
  rebuilding a whole-run lowered-operation tuple.
- [x] Validate live host operations at the block consumption boundary instead
  of traversing the complete operation source during provider setup.
- [x] Publish measurement chunks and append indices as the canonical dataset;
  sealing and terminal publication operate on small ordered digests.
- [x] Remove concrete points from the measurement contract and pass current
  admitted coverage explicitly through transforms, value closure, and record
  projection.
- [x] Let `MaterializedPointDomain` represent any contiguous ordinal coverage,
  rather than forcing temporary blocks to masquerade as a zero-based full scan.
- [x] Declare domain target resource claims before compilation, use them to form
  legal barriers, and carry them only on final run jobs; compiled artifact
  recipes and prepared invocations do not duplicate them.
- [x] Remove unknown-total and continuation policy from static execution; the
  closed point catalog is the sole total while measurement-guided admission
  remains outside the initial synchronous contract.
- [x] Seal residual compute ownership, transitive dependencies, run/point scope,
  and payload demand into one `ComputePlan`; target materialization consumes the
  verified facts instead of rebuilding graph indexes and rescanning evaluated
  state/action records for compute-result references.
- [x] Bind run-invariant compute before coverage compilation from the accepted
  configuration environment alone. A run operation can no longer accidentally
  inherit the first point's row, parameter overlay, or route binding.
- [x] Lower local work into compute operations, ordered Core-effect slots, and
  terminal collection operations; system planning schedules domain jobs in
  those same effect slots without a prefix/suffix insertion wrapper.
- [x] Derive channel and shared-group claims from final physical operations,
  without retaining a parallel route-claim ledger.
- [x] Retain operation indexes and residual value/operation closure on the
  verified semantic graph, and retain the compute plan on the verified typed
  program, so lowering does not discard verified graph facts and reconstruct
  them in each consumer.
- [x] End semantic source mapping at the semantic-to-typed diagnostic boundary;
  do not carry an unused `SourceMap` sidecar through `CoreProgram`. Preserve only
  input dependency provenance that changes specialization or compute planning.
- [x] Select the local target once: implementations, product realizations,
  instrument order, run compute operations, and the point-compute seed no longer
  get rediscovered independently for each coverage block.
- [x] Project each domain call into one static compile template and bind only its
  coverage regions and bounded input resolver per block.
- [x] Remove scan-wide point-parameter and domain-input caches. Reuse parameter
  bindings and selectively resolved columns only within the coverage whose jobs
  consume them.
- [x] Derive state barriers and action isolation before local binding from the
  compiler-owned iteration layout, then bind one representative per exact
  coverage instead of carrying barrier signatures on point wrappers.
- [x] Split resource ownership into a run lease for provider instruments and an
  exact coverage lease for point/domain claims; remove first-block compilation
  and its incomplete whole-run claim prediction.
- [x] Keep the accepted point catalog and admitted point ledger as deliberately
  different facts: static inventory for preview/source construction versus the
  observed execution prefix used for terminal records.
- [x] Remove the one-field compiled-coverage wrapper; the single-use bounded
  source yields final `RunCoverageBlock` values directly.
- [x] Analyze one compiler-owned iteration layout and project it read-only into
  `DomainIterationLayout`, preserving product, zip, known leaf extents, exact
  axes inside partially opaque grids, and opaque boundaries without duplicating
  the Core point-domain evaluator.
- [x] Align ordinary domain partitions to complete innermost sweeps when target
  capacity permits, while keeping effect barriers authoritative.
- [x] Replace point/shared-compute operation variants with one
  `RunCoverageEffect`; derive compute and state coverage from structural
  `PointVariationSupport` without a runtime memo namespace or declared
  fast/slow scope lattice.
- [x] Emit one stable state prefix per exact barrier region instead of repeated
  point operations whose only runtime result would be `skipped`.
- [x] Derive point-column variation support for parameter overlays and resource
  routes, and limit their reuse to the current coverage lifetime.
- [x] Use the compiler-owned iteration layout for parameter overlays, routes,
  local state/compute coverage, and SDK projection; opaque axes fall back to the
  currently materialized row without creating a second structural model.
- [x] Remove the speculative `factorized_jobs` recipe; target compilers decide
  artifact sharing during ordinary bounded compilation.
- [x] Remove the premature external measurement-array reference and keep arrays
  transiently in memory while allowing incremental downstream consumption.
- [x] Remove the fake post-commit coverage observer; adaptive point admission
  remains deliberately outside the closed synchronous scan contract.
- [x] Recognize finite values, grid, linspace, and range axes in the
  compiler-owned iteration layout, and retain dependent product boundaries.
- [x] Replace separate overlay/route/compute/state support passes with one
  verified `VariationAnalysis`, including support for each state effect.
- [x] Split domain compile regions only when changing state claims conflict with
  the compiler's predeclared target footprint; actions remain hard order
  boundaries and no candidate artifact is compiled then discarded.
- [x] Add explicit coverage checkpoints so resource-independent jobs may span
  local state segments without losing incremental measurement commits.
- [x] Lower state, action, and domain operations in declared Core effect order;
  delete the planning-only `BoundLocalCoverage` prefix/suffix insertion model.
- [x] Use each state effect's own variation support, merging only consecutive
  desired-state declarations, and delete the whole-program
  state-union/equality-coalescing reconstruction pass.
- [x] Preserve known axes and strides in mixed finite/opaque grids, leaving only
  unresolved columns for bounded input binding.

Artifacts, datasets, and records share one content-index model with an explicit
role, content digest, media type, and schema where applicable.
Replayable effect evidence must contain the data required by its recovery
contract; otherwise a digest belongs directly in the effect intent rather than
in a separate evidence protocol.

The interpreter emits one typed trace for observation. Durable storage records
the intent and outcome events needed for safety and recovery. UI metrics and
diagnostics are projections of that trace, not additional execution contracts.
The final run outcome, certainty, and problems are derived once at the run
boundary.

`check`, `preview`, and `run` specialize the same program. Checking and preview
may inspect a `RunProgram`, estimates, and diagnostics, but do not provision
resources or perform provider effects. Running executes that exact accepted
program or records why it could not start.

## Structures to Remove

The migration should remove, rather than adapt indefinitely:

- separate bound-plan, local-program, prepared-plan, and segment hierarchies;
- exclusive host/domain lanes and singleton domain-execution fields;
- fusion options and state-equality segment construction;
- domain callbacks injected into a local point engine;
- flat task-coverage models used to reconstruct ownership already present in
  dataflow and effect edges;
- duplicate planning-time and runtime resource claims;
- execution cache namespaces, keys, counters, and cache-status contracts;
- repeated collection chunk, measurement fragment, and dataset assembly; and
- tests whose only contract is an old IR shape, stage order, cache metric, or
  physical batch count.

Temporary compatibility layers should not be added. When a vertical slice
moves to the new model, its callers and tests move in the same change.

## Verification Strategy

Tests should concentrate on semantic laws and safety boundaries:

- interpreting a program before and after partial evaluation yields the same
  logical values;
- a parameter scan is observed identically by host and domain computations;
- host execution and valid domain specialization produce identical logical
  points and demanded products;
- different valid physical job partitions produce the same logical results;
- no domain job crosses a changing state, action, or resource barrier;
- every opaque target result location maps to exactly the required logical outputs;
- intent precedes each consequential effect;
- rejected and unknown effects have distinct retry behavior;
- abort and cleanup preserve their documented ordering; and
- check, preview, and run consume the same specialized program.

Focused boundary tests should remain for provider receipts, storage failures,
corrupt result mappings, and recovery. Exact internal node sequences are only
tested where they are themselves the compiler contract.

## Completed Migration Sequence

1. Encode the semantic invariants above as reference-evaluator and effect-safety
   tests. Remove assertions that exist only to preserve the old engine shape.
2. Replace mutable point-local parameter overlays with lexical typed bindings.
   Prove that one scanned parameter has identical host and domain semantics.
3. Introduce `CoreProgram`, its symbolic point space, and partial evaluation.
   Keep residual point loops symbolic under a materialization budget.
4. Implement one domain compiler vertical slice that lowers a parameter scan
   into a native target list or table while preserving exact logical output
   mapping and state barriers.
5. Introduce the single `RunProgram` interpreter, resource owner, and effect
   journal. Move host and domain effects into that program.
6. Move canonical measurement persistence and terminal outcome derivation to
   the new run boundary.
7. Delete fusion, lanes, coverage reconstruction, duplicate plans, callbacks,
   runtime cache contracts, fragment reconstruction, and the old engine.

Normal execution no longer constructs or adapts the old plan and engine models;
the sequence above is complete. Further changes should be justified by a newly
identified semantic boundary or by measurable implementation reduction, not by
preserving an intermediate phase name.
