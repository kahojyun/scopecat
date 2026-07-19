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
owns one ordered effect sequence, and `RunProgram` owns one explicit ordered
operation sequence interpreted without reconstructing host/domain regions at runtime.
Normal execution does not construct the former bound-plan, prepared-plan,
segment, lane, fusion, coverage-reconstruction, execution-cache, or
measurement-fragment models.

Point composition remains symbolic through verification and specialization.
The synchronous initial runtime closes the accepted run's logical point and
result mappings during `RunProgram` compilation under an explicit
`max_materialized_points` budget. Domain compilers receive complete specialized
program inputs, exact barrier ordinals, supported point-axis normal forms, and
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
artifact. The system's compiler receives one immutable compile request, which is
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
Canonical
Core scalar, series, and relation AST nodes are no longer exposed to domain
adapters. Exact finite
literal axes are projected with compact ordinal repetition metadata across
product and zip composition, allowing a target to lower an affine scan without
binding its domain input or expanding a Cartesian product. Dependent and other
unproven shapes may still use the bounded binder; unrecognized inputs remain residual.
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

Config-bound route and constraint data used during specialization is temporary
planning data, not compiler linking IR or an executable plan. Local
materialization and route constraint validation live at the planning boundary,
where they directly construct final execution operations. Provider ABI
description precedes
host point materialization, so planning has the final instrument order while
constructing final point stages. Local materialization produces only a transient
planning value; the former executable-looking `LocalExecutionPlan` and its
structural program protocol have been deleted. Blocking diagnostics raise
`CheckFailed` at that boundary. `RunHostBinding` contains provider provisioning
data and selected product identities, but no duplicate point or product
inventory. Point execution is written once into the final operation stream as
explicit start, stage, and end operations. Mixed runs interleave domain jobs in
that stream without copying a point into phased prefix and suffix programs or
reassembling half-points in the interpreter. Domain lowering writes
`RunDomainJob` operations with exact logical-point and product correlation.
Contiguous host-only execution is retained as one budget-closed `RunPointLoop`
rather than expanding every start, stage, and end into the outer operation
tuple. Interpretation, provider validation, and measurement binding consume
that loop through one lazy atomic-operation iterator; mixed effect barriers
remain explicitly interleaved.
Local and domain resource claims are consumed while constructing the final
`RunProgram`; only its unified claim set reaches execution. The run boundary
acquires that set once, and the effect interpreter no longer carries a second
claim inventory or an internal no-op lease layer. Host-backed and domain-only
programs enter one provisioning-and-interpretation function and return one
execution outcome containing setup diagnostics, logical domain candidates, and
any captured domain failure; the run boundary no longer maintains separate
host/no-host interpreter branches or parallel result side channels.
`DomainCompiledJob` and its generic artifact slot end at `prepare`; target data
needed during effects must be closed explicitly into the invocation payload.
Compile-time resource claims are merged into the final `PreparedDomainExecution`,
leaving each domain run operation with one prepared payload rather than parallel
compiled and prepared representations. The rich `DomainBatchContext` also ends
at this boundary; only closed invocation, output, transform, runtime, and resource
data enter the `RunProgram`. Preparation no longer carries a side-channel object
identity after the context-bound builder has closed those values.
Raw point rows, selected-product realization objects, and nested compute result
wrappers are discarded at the binding boundary instead of being mirrored into
another plan API. Resolved routes are likewise temporary: materialization
uses them to validate point-local constraints, bind final effect fields, and
close run-level instrument/channel/group claims once. The former `BoundPoint`
model has been removed, and `PointProgram` carries the canonical
`LogicalPointId` directly. `ResourceClaim` is a shared
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
models and their conversion pass have been removed; planning groups the already
topologically ordered operations into `ComputeStage` immediately.
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
`RunProgram` retains that inventory only through one `MeasurementProjection`.
That planning value closes product-value selection and record projection over
the same catalog in one operation, so the program no longer echoes point
catalog, values, and projection as parallel fields. Runtime projection produces
one `MeasurementRecordBatch`; successful persistence returns the committed
records directly, while receipts remain journal and repository evidence instead
of becoming another successful-result wrapper.
The former `local_semantics` module and `materialize_local_semantics*` API names
have also been removed: final local execution is produced by
`materialize_local_execution*`, while short-lived `PendingRoute` values live
only beside their planning constraint checks.
Mixed runs encode point prefixes, domain jobs, and point suffixes in program
order instead of invoking a separate region engine. Canonical measurement
candidates from both placements are sealed once at the run boundary.

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
The experiment system's explicit domain compiler runs directly from the specialized
`LinkedPlan` before full point materialization whenever symbolic cardinality is
exact. A compiler can partition logical ordinals without resolving
inputs, or resolve a selected input set through one normal-form-first API. One
ordinary lowering boundary now owns capacity partitioning and invokes the
target artifact compiler once for each resulting barrier-contained partition;
it also supplies each artifact compiler with its selected resolved columns and
aggregates binder provenance into the compilation result. Inputs requested for
artifact lowering are absorbed by construction, so adapters do not repeat the
same ids as a separate claim; explicit absorption remains available for
structure or literals that need no resolved column. Adapters no longer
construct a parallel partition list or maintain a side-channel binding ledger.
Literal point leaves in independent products and
positional zips additionally expose exact finite column axes with compact
ordinal repetition, without invoking that binder. A shared linking-layer
materializer closes the point
domain at most once, resolves parameter overlays and domain inputs only for
requested ordinals, and reuses those cached bindings when host materialization
and domain preparation later complete the plan. Exact-cardinality point spaces
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
action effects before implementation selection. Execute-stage, run-rate host
computations are bound once, written as an explicit `RunComputeStage`, and made
available to every point frame rather than being copied into each iteration.
This provides structural sharing across the point loop without a runtime cache.
Payload-producing compute remains point-rate because its durable payload
evidence is point-scoped.

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

The compiler tracks at least these binding times:

- request-static: accepted invocation inputs and capture-time constants;
- configuration-static: values from the accepted configuration snapshot;
- point-varying: values determined by a logical point or scan axis;
- execution-time: live state and external effect results; and
- result-time: acquired or derived result values.

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
effect-demand closure. Opaque execute-stage computations remain explicit
point-rate operations until the run IR has a first-class run-rate compute
operation; relabeling them as hoisted would not be a valid lowering.

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
domain calls to different physical targets. Each prepared invocation closes the
actual downstream target compiler and physical target, which become authoritative
for resource claims, execution, and provenance.

The core provides a domain compiler with:

- the typed domain body and ports;
- complete typed program inputs with SDK-owned normal forms or an opaque marker;
- supported symbolic point-axis projections in SDK-owned normal forms;
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
mapping uniqueness, resource claims, and barrier containment.

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

The successful recording operation returns the exact committed canonical
records, which feed dataset validation, terminal evidence, progress, and
manifest construction directly. Repository reload is reserved for uncertain or
partial recording recovery; it is no longer part of the normal terminal path.

### Completed simplification checklist

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
- [x] Bind run-rate compute exactly once and point-rate compute once per logical
  point; evaluate state and action expressions in that same point pass rather
  than building and regrouping whole-run temporary record lists.
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
- every physical result maps to exactly the required logical outputs;
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
