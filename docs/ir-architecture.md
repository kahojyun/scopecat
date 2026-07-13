# Layered Transient IR Architecture

Status: accepted direction

Scopecat will evolve from a sequence of convenient compiler records into a
small set of orthogonal, transient intermediate representations. Each layer
owns one kind of decision and lowers in one direction. No one representation
is expected to serve authoring, relational evaluation, hardware placement,
and durable execution evidence at once.

This decision is intentionally made before Scopecat needs hardware offload, a
second relation backend, or a first-class quantum DSL integration. Those
features are not immediate deliverables. They are design pressure used to
avoid making the current local Python execution model the permanent semantic
model.

## Context

The current compiler has useful typed boundaries, but several records still
carry facts from multiple layers:

- module composition expands instances and rewrites identities while it
  collects declarations, resource requirements, and record policy;
- value references combine definition identity, type, source expression,
  ownership, provenance, and dependency closure;
- relation nodes originally described operations and also knew how to evaluate
  themselves with the local Python implementation; the first relation-boundary
  slice described below has removed that coupling;
- compute meaning and execution constraints now survive lowering in an
  implementation-independent `OperationContract`; local lowering seals exact
  Python implementation coverage and no longer carries the candidate catalog
  into the bound plan;
- compute operation identity and produced-value identity now remain separate
  from the semantic graph through typed, bound, and local execution IR;
- the current local planning lowering materializes every point before
  execution, although linking no longer requires that materialization;
- the execution program interleaves the current host-controlled scan,
  acquisition, and postprocessing order rather than exposing a closed
  domain-program invocation boundary.

These choices are reasonable for the first local executor, but together they
make flattening observable and make Python execution, point materialization,
and local placement appear to be domain semantics. Extending those records in
place would create a universal IR whose fields have incompatible lifetimes and
owners.

## Decision

The transient compilation pipeline will have four compiler layers followed by
target-specific artifacts and runtime protocols:

```text
Python DSL or domain adapter
          |
          v
      Module IR
          |
          v
   Semantic Graph IR
          |
          v
      Linked Plan
          |
          v
Host Orchestration Plan
          |
          +----> Local ExecutionProgram
          |
          +----> Domain invocation ----> target artifact
```

Lowering is one-way. A lower layer may carry explicit provenance pointing to
an upper-layer construct, but it must not depend on upper-layer Python handles
or recover semantics by parsing names. Durable run records are projections of
accepted intent and execution evidence; they are not another IR layer.

Scopecat is a host orchestration and data-model compiler, not a universal
control-flow compiler. Its generic core owns declarative outer scans that do
not participate in real-time feedback, host-visible resource and product
contracts, and data postprocessing. Loops, branches, adaptive feedback,
shot-level control, timing, and other domain-specific control flow belong to a
domain program and its compiler. Offload may move adapter-approved core work
into such a program, but that is a semantics-preserving fusion across an
explicit boundary, not a requirement for the core IR to represent the domain
program's internal control-flow graph.

### Layer 1: Module IR

Module IR preserves composition boundaries until an explicit linking or
flattening pass. Its conceptual model is:

```text
Module
  interface
    value imports
    value exports
    logical resource requirements
    available measurement products
  body
    value and operation declarations
    nested module instances

ModuleInstance
  instance identity
  input bindings: import -> value use
  export projections: exported name -> inner value
```

Imports, exports, definitions, and uses are distinct constructs. An export is
an interface edge to a definition, not a copied value declaration. An import
is an unfulfilled interface requirement until an instance binding supplies a
use. Template-level choices such as scans, exposed defaults, and durable record
selection remain outside reusable module bodies.

Composition is hygienic linking. It must preserve nested instance identity and
producer provenance even when local names, instance names, or domain IDs
contain punctuation. Flattening is permitted only as a named compiler pass
whose semantic equivalence is tested.

### Layer 2: Semantic Graph IR

The semantic graph is a typed dataflow and effect graph independent of module
syntax, configuration, placement, and evaluator implementation. Its minimum
vocabulary is conceptually:

```text
SymbolId       = structural scope plus local identity
ValueDef       = id, value type, availability, defining operation or source
ValueUse       = referenced ValueDef id
Operation      = id, operation contract, input uses, output definitions
EffectEdge     = explicit ordering or conflict dependency
SourceMap      = IR identities -> source and composition provenance
```

`SymbolId` is structural and injective. It is never reconstructed from a
delimiter-packed display string. It is an address within a typed symbol space,
not a universal namespace: value, operation, and logical-resource identities
use nominal wrappers or equivalently typed fields, so equal-looking names in
different declaration categories cannot alias accidentally. Declaration
identity is separate from every use of that declaration. Type,
planning/execution stage, update rate, portability, effect class, and placement
constraints are independent facts. Provenance and source locations live in
side tables so diagnostic needs do not distort semantic equality.

An operation identifies what it means, not how a particular backend executes
it. The implemented `OperationContract` groups four independently checkable
facts: semantic meaning, effect class, portability, and placement constraint.
It deliberately contains no operation identity, ports or value types,
provenance, implementation identity, backend identity, or cache policy. The
same immutable contract value is retained by `SemanticOperation`,
`TypedComputeNode`, the program snapshot in `LinkedPlan`,
`BoundComputeCall`, and the local `ComputeOperation`. Semantic-graph checking
and Typed Program sealing both validate the contract; the latter also rechecks
the shape and scalar types required by portable scalar-binary semantics.

A Python callable, vectorized relation implementation, compiled circuit, or
device program is an implementation selected during lowering.
`IMPLEMENTATION_DEFINED` does not mean Python, `PORTABLE` does not prove that
a target supports an operation, and `UNCONSTRAINED` does not itself select a
placement. These are semantic constraints and capabilities consumed by a
later target policy, not target-acceptance evidence. Implementation-defined
operations remain valid; portability is explicit rather than a requirement
imposed on all compute. A portable operation may still carry a narrower
`HOST` placement constraint without losing its portable meaning.

Operation identity is also not result identity. `OperationId` names a semantic
operation; local target lowering derives a separate point-local invocation
coordinate from the logical point and that operation. `ValueId` names a value
defined by one of its output ports. Typed compute edges therefore close against
an exact `ValueId`, retain the consumer's expected type, and resolve that value
to its owning operation only when graph ordering or provenance requires the
owner.
The exact result identity, type, and availability survive into `BoundPlan`, and
local execution reads and writes compute results by `ValueId`. Renaming only a
result value may change provenance-facing payload coordinates, but it does not
change operation meaning, input semantics, or the compute cache key.

The current `TypedComputeNode` and local Python lowering deliberately support
one result per operation. That is a target-lowering restriction, not an
identity shortcut: the result is an explicit typed definition rather than an
anonymous `output_type` attached to the operation. Semantic Graph IR already
models named output ports. A future multi-result target may widen the typed
result inventory without changing edge identity or reconstructing values from
operation names. Local Python selection currently accepts only execute-stage,
point-rate results and rejects other availability before any relation
evaluation or point materialization.

Host-observable effects are represented separately from data dependencies.
Resource mutation, domain invocation, measurement, submission, fetch, and
cancellation therefore cannot be reordered merely because their values form an
acyclic dataflow graph. Domain-program values and the effects that invoke them
are distinct. Internal loops, branches, feedback, shot iteration, and timing
remain in the domain dialect IR rather than expanding into core control-flow
nodes.

### Layer 3: Linked Plan

The linked plan records successful program closure and accepted configuration
while retaining a symbolic point domain. It closes semantic references and
checks every used typed parameter import against the accepted environment. It
also validates logical resource, capability, and product contracts
structurally while retaining the complete verified relation-use inventory.
Relation-backend selection and point-dependent logical-to-physical routing
remain lowering decisions.

```text
LinkedPlan
  sealed backend-neutral VerifiedTypedProgram
  accepted config snapshot and parameter environment
  symbolic PointDomain algebra
  logical resource and routing intents
  available product definitions, demanded uses, and record projections
```

`PointDomain` now uses the shared ordered algebra `Unit`, `RelationRows`,
`Product`, `DependentProduct`, and `Zip`. Authoring and compiler IR preserve the
same composition tree with different relation-leaf payloads. Structural shape
analysis projects schemas and cardinality bounds without asking a relation
backend to implement domain composition. Only `RelationRows` leaves require
relation proofs and backend selection; product, dependency, and positional
composition remain point-domain semantics.

`VerifiedPointDomain` owns the checked tree, per-node shape facts,
entity-column roles, and exact relation-leaf proofs. `VerifiedTypedProgram`
retains those leaves together with every other executable relation consumer.
Every executable occurrence carries a nominal `RelationUseId`. Semantic kind,
value, and diagnostic `ModelLocation` remain separate inventory facts;
structural position affects the diagnostic location but not identity. Moving an
occurrence therefore cannot transfer a later backend selection to a sibling.

The current local lowering performs whole-program relation preflight by pairing
the complete inventory with one backend, producing `SelectedPointDomain` and
`SelectedTypedProgram`. The selected program requires exact identity coverage,
the original verified owner and proof, one backend, and reuse of the same
whole-program selection for point-domain leaves. No leaf is evaluated while
that selection is incomplete. A future domain lowering may instead produce a
target-specific exact coverage proof for adapter-fused uses; it must not claim
`SelectedTypedProgram` unless one backend owns the complete inventory. A
`MaterializedPointDomain` is a separate local lowering that preserves canonical
relation order and duplicates; it is not a mathematical set.

The implemented `LinkedPlan` is the success boundary between those phases. It
retains the sealed verified program, its still-symbolic point-domain tree, and
a defensive snapshot of the validated configuration environment. Linking
closes and verifies the program, validates the complete relation inventory's
used scalar, series, table, and lookup parameter contracts, but does not choose
a relation backend. It also does not materialize points, bind point-local
compute calls, resolve point-local routes or state, or build local collect
operations. Generic linking validates local implementation identities and
operation ownership plus each candidate's declared operation contract as
sidecar structure, but it neither requires complete local Python coverage nor
chooses among local Python candidates. Missing backend capability, or a missing
or ambiguous local Python implementation, therefore does not prevent production
of a target-neutral `LinkedPlan`; a malformed proof or candidate declaration
still fails earlier.

`materialize_local_plan` performs the current local target decisions as an
independently callable lowering. It selects one relation backend for the exact
whole-program inventory and requires one unique local Python implementation for
every compute node. It aggregates both selection failure families before any
relation or point is evaluated. Successful implementation selection produces a
token-sealed `SelectedLocalImplementations` artifact with complete, unique
coverage in verified typed-node order. Each entry pins operation identity,
implementation identity, contract, typed input/output interface, and the exact
callable. The aggregate survives even for a zero-point plan, while each
point-local `BoundComputeCall` retains the exact selected entry. `BoundPlan`
therefore carries only selected implementations and the selected relation
backend identity, never either candidate catalog. Local execution lowering
directly projects the pinned callable and identity into `ComputeOperation`; it
performs no second catalog scan or uniqueness decision.

The structural contract and typed-interface fingerprints both participate in
each compute cache key, so changing operation meaning, constraints, or port
types cannot reuse a cache entry merely because operation, implementation, and
input identities stayed equal. The callable itself is deliberately not
hashed: publishing different behavior under the same `ImplementationId`
violates the implementation provider's versioning responsibility.
`bind_program` only composes `link_program` with this local lowering. A future
domain lowering may consume the same successful `LinkedPlan` without first
constructing a tuple of local points or satisfying local Python coverage.

The same linked plan may be consumed by different backend or target lowerings.
Each lowering must establish complete, non-overlapping implementation ownership
for the full relation inventory before evaluating the first consumer or
producing a target artifact. The current local path seals one exact backend.
Selected-plan dispatch also reassesses that backend's requirements, so a
backend whose capabilities change after selection cannot bypass the gate or
partially execute under stale evidence.

Each materialized point receives a nominal `LogicalPointId` from the domain
namespace and its canonical logical ordinal. A local `point_index` is currently
the same ordinal, but is only a local execution projection. Point identity does
not depend on whether every row value has a content fingerprint. Optional row
content keys may support comparison or caching, but cannot define whether a
logical point exists. Future batches and target result mappings must carry the
already assigned identity and must never enumerate a batch into a new identity
space.

Authoring scan dependencies now have a config-free proof boundary before that
compiler IR. `VerifiedScanDependencyGraph` records unique axis providers,
typed producer-to-consumer edges, original composition paths, and a stable
topological order. Cartesian regions may be reassociated to satisfy explicit
dependencies, while independent axes retain declaration order. Positional Zip
branches cannot consume sibling outputs. Missing providers, self-dependencies,
cycles, incompatible provider types, and composition cycles are therefore
authoring problems rather than late relation-verification failures. This pass
also treats an existing module point domain as a peer factor that both provides
and consumes typed coordinates, instead of imposing an input/base/extra phase
order. Its normalized composition lowers directly to the point-domain algebra;
it does not encode domain composition as relation `point_cross` or `zip`
operations. Transient `ValueRef` metadata keeps total point provenance separate
from the remaining free point/input interface, so internally satisfied
dependencies are not confused with root self-dependencies.

This is a real symbolic linking boundary with an implementation-independent
compute contract, but it is not yet a target-selected orchestration plan.
Executable relation-use identity is now independent of diagnostic paths
and sibling position across point-domain leaves, parameter overlays, routes,
compute inputs, and state.

The logical/physical resource identity boundary is now implemented across the
transient compiler path. `LogicalResourcePortId` nominally wraps a structural
`SymbolId`; `PhysicalResourceId` nominally wraps an ID from accepted
configuration. Route declarations and bound routes retain both identities.
State targets explicitly discriminate a logical port from a relation that
produces a physical ID, while product producer targets use the corresponding
nominal sum. Equal display text in the two namespaces therefore cannot alias,
and no lowering may infer which namespace a value belongs to by comparing
strings.
Resolved routes also retain the physical resource kind, selected entity IDs,
the resource's served-entity domain, and exact channel mappings. Entity
selection is independent of channel selection: state and collection effects
carry both, so a channel-free entity target is not erased and a product cannot
inherit unrelated channels merely because two ports resolve to one instrument.
Routing topology is capability-indexed. An explicit binding for one capability
is authoritative for that capability across the resource; resource-level
entity/channel pairs are used only when that capability has no explicit
binding topology. Capability-specific entity declarations narrow the fallback
domain, exact duplicate bindings normalize to one target, and contradictory
topology for the same physical target is rejected during configuration
validation. A capability-unspecified record unions the resulting physical
targets and removes capability-only duplicates without inventing cross-product
bindings.

Typed Program sealing closes logical state and record references against the
declared route-port inventory and checks their required capabilities. Linking
checks statically named physical record targets, fixed route targets, and
literal physical state targets against accepted configuration without
evaluating a relation. Local materialization validates dynamically evaluated
physical state targets directly against the routing view; it never falls back
to a same-named logical route. A valid `BoundPlan` requires each point to cover
the complete ordered logical-port inventory, so losing or duplicating a route
is not representable as successful planning. Durable and runtime projections
unwrap these nominal identities only at their explicit boundaries and label
logical ports separately from physical resources.

The logical product boundary is implemented as four orthogonal graph
constructs:

```text
InstrumentProductProducer --produces--> ProductDef --referenced by--> ProductUse
          |                                                            |       |
          +---------------- target selection --------------------------+       |
                                                                       |       |
                                              selected realization ----+       |
                                                       |                       |
                                                       +--> CollectionRequest  +--> RecordUse
```

`ProductId` nominally wraps a structural `SymbolId`; equal-looking products in
different module scopes therefore remain distinct. `ProductDef` declares an
available logical output and is the sole owner of its kind, unit, dtype, axes,
and logical product metadata. Definitions survive linking even when no
consumer selects them. `InstrumentProductProducer` is a separate edge with
its own nominal `ProductProducerId`; it owns the resource/capability target,
provider-facing key, and adapter metadata needed to produce one `ProductDef`.
Neither identity contains the other as an accidental string convention.
Public record and product declarations expose logical `metadata` and
`producer_metadata` separately, so dataset annotations cannot silently become
provider request options or vice versa.
`ProductUse` is a fresh occurrence-level demand for one definition. It carries
neither a record name nor acquisition policy. `RecordUse` is the
template-owned projection from that occurrence to a durable output name and
record-only metadata. One use may feed multiple record projections without
duplicating the underlying work; a use may also have no record projection when
another later consumer needs the result. Public authoring exposes the shared
projection case explicitly through `record_alias`; selecting the same product
again creates a distinct use occurrence rather than silently coalescing work.

Typed Program sealing checks product and producer uniqueness plus exact
producer-to-definition, use-to-definition, and record-to-use closure before
configuration or effects. A definition may have zero or several producer edges
in this target-neutral graph. `LinkedPlan` retains all four inventories without
deciding how a use is produced, and an unused producer creates no placement or
effect requirement. The current local lowering first seals
`SelectedLocalProductRealizations` with complete use coverage, requiring each
demanded observable to have exactly one instrument producer before relation
evaluation or point materialization, and then realizes every accepted use once
per logical point as a `CollectionRequest`. Each sealed entry binds exact
snapshots of both the accepted `ProductDef` and the chosen producer; when
resource selection is implicit, it also pins the uniquely resolved physical
instrument.
That request has `ProductUseId` and `ProductId` but deliberately has no record
ID. Provider keys are producer-adapter coordinates rather than semantic or
durable identities, and conflicts are checked only after physical placement is
known. A product without an explicit resource must resolve to one configured
instrument; implicit broadcast is not a valid realization of one use.

Local execution preserves the same separation. A provider response key maps
first to `ProductUseId`; only after collection succeeds do
`RecordProjection` edges copy the logical result to one or more observable
record IDs. A future domain adapter may instead map a use to a domain-program
output, fused postprocessing result, or target result slot. That substitution
must preserve `ProductId`, `ProductUseId`, logical point identity, and the
record projections; it must not make the current provider key, collection
command, or host stage order part of generic product semantics. Transient
product-use identities are projected at explicit runtime boundaries and are
not added to durable run schemas. Producer provenance is projected by run-plan
and preview models as a typed `producer_kind`, while `RecordPlan` and dataset
schema remain
producer-neutral: record aliases, provider coordinates, and placement cannot
change the logical variable schema.

`InstrumentProductProducer` is deliberately a concrete local acquisition edge,
not a universal domain-output or quantum-result ABI. When a real domain
integration arrives it should add a different producer/realization shape and a
target-specific selection proof; it should not grow source variants, backend
flags, or domain control concepts on `ProductDef`. Relation-backend selection
and product-realization selection remain separate coverage proofs even when one
domain adapter can discharge both.

Two distinct symbolic targets cannot co-own one mutable physical state slot;
such aliasing is a planning conflict even when both request the same value.
This keeps the singular logical provenance carried by bound state, preview,
and durable v4 honest. The durable record rechecks route closure, physical
resource kind, capability ownership, selected/served entity domains, and exact
state channel targets rather than trusting a structurally valid JSON shape.
Provider preflight also rejects an unqualified product key that matches more
than one capability instead of selecting the driver's first declaration.

The remaining resource work belongs to later layers rather than identity
repair: a domain invocation still needs explicit logical resource claims,
execution ownership, target capability proofs, and a mapping from target jobs
back to logical points and products. External configuration, driver ABIs, and
durable JSON continue to use strings intentionally; those strings are decoded
or projected at typed boundaries and are not transient IR identities.

The local effect ABI mirrors this target identity. Scoped state commands,
snapshots, planned changes, and collection requests retain entity IDs and
channel bindings; reconciliation keys include that complete target rather than
only capability and field path. Point-local topology constraints and execution
leases are derived from routes, desired state, and collection products, so a
direct physical target cannot bypass a shared channel or group claim.

The local sealed selection proves which declared callable was chosen, that its
owner and declared contract match the typed operation, and that the selection
has exact graph coverage. It cannot prove arbitrary Python behavior by
inspecting a callable. Before pinning that callable, the current local selector
only checks the declared contract's intrinsic consistency, supported semantic
kind, effect, and placement. It does not inspect Python signatures or prove a
general target capability relation. A future hardware or domain target must
introduce its own capability and artifact proof in response to a concrete
workflow. This limitation does not restore local Python coverage as a
condition for creating `LinkedPlan`.

The linked plan therefore proves closure, accepted configuration, symbolic
domain preservation, a complete verified relation inventory, and preservation
of each compute operation contract. It does not prove that a relation,
hardware, simulator, or domain backend accepts those contracts, and it does not
constitute a target-selected orchestration plan.

Logical point IDs and product IDs are stable across legal materialization,
fusion, batching, and out-of-order result delivery. Physical target
coordinates and backend job indexes are mappings to those identities, not
replacements for them.

### Layer 4: Host Orchestration and Domain Invocation

This layer describes only the host-visible orchestration boundary. It orders
coarse effects such as host scan preparation, one or a small number of closed
domain invocations, result acceptance, postprocessing, and recording. It is not
a generic fragment scheduler and does not reproduce a domain program's internal
control flow.

```text
HostOrchestrationPlan
  host preparation and postprocessing regions
  closed domain invocation effects
  logical point/batch inputs and product outputs
  logical resource claims
  target capability and mapping proofs
  host-visible effect ordering
  retry and uncertainty contract
```

The current implementation may continue lowering directly to the synchronous
local execution program. When a concrete domain integration arrives, the first
additional shape should be one closed domain invocation plus host-side
submission, collection, and reconciliation. The domain program owns its loops,
branches, feedback, timing, shots, and device-local error handling.

Offload means that an adapter proves selected pure scans, computations,
collection setup, or postprocessing can be fused into that invocation while
preserving their logical contracts. It does not mean splitting arbitrary core
graph regions across arbitrary targets. Fusion must not change logical point
identity, product contracts, host-visible effect ordering, or observable value
semantics. Unsupported fusion or target capabilities fail during checking or
lowering, before external effects.

### Target artifacts and runtime protocol

A target compiler is pure: it turns an accepted domain-program invocation and a
declared target description into a prepared artifact or structured problems.
The effectful, host-visible runtime boundary is separate and may eventually
support prepare, submit, inspect, fetch, cancel, and reconcile operations.

Target evidence must relate opaque durable submission/job identities and
result chunks back to logical point and product identities. Host journal
transitions record effects controlled by the host. Device-internal traces are
attached target evidence, not fabricated host transitions.

The existing local `ExecutionProgram` remains a valid target-specific lowering
for synchronous execution. It ceases to define all legal execution semantics.
Nor does Scopecat need a universal replacement for it: a domain adapter may
keep its internal control IR private and expose only a checked invocation
boundary. The operation-contract slice does not introduce a hardware placement
model, target capability description, quantum dialect ABI, compiled-artifact
format, or runtime submission protocol. Those boundaries remain driven by a
concrete offload or domain-integration workflow rather than speculative fields
on the current contract.

The current synchronous `CollectReceipt` is correlated to its command only by
the in-process call stack. It does not echo a command digest, operation,
attempt, or logical point identity, so this trust assumption must not be reused
for remote, cached, asynchronous, or offloaded results. A future target runtime
protocol must authenticate or otherwise correlate every receipt/result chunk
to the submitted artifact and map it explicitly to logical point and product
use identities before acceptance.

## Dialects and Backend Boundaries

The semantic graph has a small generic core and explicit dialect operations.
It will not grow a core variant for every relation operator, quantum gate,
pulse primitive, or vendor job type.

### Relation plans

The first relation-boundary slice now represents relation semantics as a
data-only plan family. The current private records are `ScalarExpr`,
`SeriesExpr`, and `RelationExpr`; together they are the conceptual
`RelationPlan`. They contain declared operations, literal data, references, and
construction-time shape checks, but no evaluator or backend policy. One
exhaustive relation analysis owns child traversal, reference collection, scope
checking, and the capability identity of every scalar, series, and relation
operation. Compiler consumers must not grow private walkers over the same plan
shape.

Row references have three distinct meanings:

- a point reference reads the experiment point and cannot be captured by a
  nested relation row;
- a current-row reference reads the row introduced by the nearest relation
  binder;
- an outer-row reference deliberately reads an explicitly supplied enclosing
  lexical row.

Callback-bound current-row references additionally carry a nominal
`RowScopeId`. The identity is structural and participates in scope checking; it
is not reconstructed from a column name. Consequently an equal-looking column
in another callback cannot satisfy the reference accidentally. Unscoped
current-row references remain available only at boundaries that explicitly
provide a current row. Module instantiation alpha-renames both binders and
references with the instance scope, so copying a module cannot collapse two
nominal row regions. Row-dependent scalar values carry `ValueRate.ROW`, rather
than being mislabeled as run- or point-rate values.

`Cross` and `LateralCross` are separate operations. `Cross` evaluates both
inputs independently. `LateralCross` explicitly allows the right plan to read
the current left row. A backend may support one without supporting the other;
ordinary Cartesian-product syntax must not acquire correlation merely because
the reference implementation happens to use nested Python loops.

The relation language retains a third, internal operation, `PointCross`, for
plans that deliberately extend only the right plan's point namespace. Unlike
`LateralCross`, it does not turn the left row into a current or outer relation
row. The point-domain algebra no longer uses this relation operation to encode
domain composition; `DependentProduct` owns scan-axis dependency instead.

Evaluation belongs to a `RelationBackend`. `ReferenceRelationBackend` is the
deterministic Python implementation and defines the current observable
semantics. Each backend declares its supported relation operations. A
capability gate walks the complete plan and rejects every unsupported operation
before evaluation; backend selection is compiler policy and never silently
falls back to the reference implementation. Final Typed Program verification
puts the complete executable inventory in `VerifiedTypedProgram`, which enters
the successful backend-neutral `LinkedPlan`. A lowering that delegates relation
evaluation to a `RelationBackend` selects it against that inventory.
Config-dependent record-axis size and metadata folding is an explicitly
separate host-static authoring phase with reference semantics; it neither
selects nor silently falls back from the target backend.
Backend selection consumes `VerifiedRelationPlan` and returns a sealed
`SelectedRelationPlan`; backend identity is intentionally absent from the
backend-neutral proof. Selection consumes a
`RelationPlanRequirements` projection: the certified root type, every
occurrence-level type fact, typed imports, external row interface, required
operations, and named runtime obligations. Operation and obligation rejection
is centralized; backends provide a structured policy over the full type
requirements rather than a second lossy atom/schema capability enum. This
matters for plans whose bounded root contains an unbounded intermediate input.
Capability failures retain dimension, code, plan path, and message.

Typed Program point-domain rows, overlays, routes, compute values, and recursively
nested state values now own proof-carrying shape envelopes. Input substitution,
semantic-operation inlining, scan composition, and state-region lowering all
freshly verify the transformed AST against the final consumer contract and its
role-specific `RelationTypeBindings`; no raw expression can enter executable
IR. Point sources receive imports but no pre-existing point row, point-local
consumers receive the final point-row type, and state bodies additionally
receive their current and nominal row arguments. The compiler no longer repeats
a weaker raw-AST scope pass after this boundary. Typed Program verification
rechecks every stored proof under the exact row roles its consumer supplies;
`seal_typed_program` snapshots that normalized program as an unforgeable
`VerifiedTypedProgram`. One recursive consumer inventory is shared by role
verification and backend planning, covering point-domain rows, overlays, route
entities, compute value inputs, and every nested state
relation/resource/value/route entity.
`select_typed_program` selects each inventory entry once and produces a sealed
`SelectedTypedProgram`. The current `materialize_local_plan` lowering aggregates
capability issues with their consumer identity and exact model/plan path as
blocking planning problems, together with local implementation-selection
failures. It performs no relation evaluation unless both complete selections
succeed. Other target lowerings may apply different implementation or fusion
policy to the same `LinkedPlan`, but must preserve exact use coverage and this
all-or-nothing preflight property.
`ValueInput.origin_input_ids`
remains a separate pre-rewrite provenance edge; it is not reconstructed from
the final proof imports after inputs become literals or point columns.

Module-level evaluators accept only `SelectedRelationPlan`; backend
materialization hooks accept a sealed `PreparedRelationEvaluation` created by
the validated dispatch boundary. The reference backend unwraps that prepared
proof inside the backend module; there is no generic raw-AST or unchecked
context dispatch hook. Selection and unwrap both reassess the full
requirements, so replacing a backend instance with the same identity but
narrower capabilities cannot bypass the gate. Before dispatch, actual used
inputs, parameters, point/current/outer rows, and nominal row arguments are
validated, normalized, and snapshotted against the proof assumptions. Scalar,
series, and table results are normalized against the certified root type and
checked for valid runtime carriers, so a backend cannot silently violate the
contract it accepted.

The proof and selection projection expose an explicit external row interface
separate from value imports. It distinguishes point, current, outer, and named
row arguments; retains the exact referenced column paths, their projected root
types, and open-row semantics; and marks operations such as `point_cross` that
observe a complete incoming row. Plan-local row binders and point columns
introduced by a point cross do not leak into this interface. Whole-program
backend preflight is therefore complete within each concrete lowering before
its first executable relation is materialized.

State iteration is represented by an explicit `StateEachRegion`. The region
owns one typed nominal row argument, a relation use evaluated before that
argument is introduced, and real resource/value/route uses evaluated in the
region body. Row-dependent `ValueDef` and `SemanticOperation` declarations have
one lexical owner; global declarations have none. Visibility permits global or
same-region declarations, while capture from another row region is rejected.
Nested semantic row regions are deferred until their lowering has a concrete
consumer. `PlanExpressionSource` therefore contains no use-site scope summary:
free row uses are derived lexically after subtracting plan-local binders such as
filter and with-columns callbacks.

The linked semantic experiment no longer retains a second flattened
`state_intents` projection. State lowering consumes verified regions, so the
binder, body uses, ownership, and state operation cannot drift between two
truth sources. Module IR still owns source-level state intents before explicit
linking and alpha-renaming.

Typed relation verification is now a backend-neutral proof boundary. A
bidirectional verifier infers a type for every scalar, series, and relation node
while using the consumer type to resolve contextual null and empty literals.
It closes typed input and parameter imports, point/current/outer rows, and
nominal row arguments. `RowType` represents one structural row without
smuggling table cardinality or primary-key facts into lexical scope. Parameter
lookups import an exact `ParameterLookupSignature` rather than pretending that
a projected lookup contract is a complete table schema.

The module-private sealed `VerifiedRelationPlan` retains a defensive root, the
consumer-facing certified type, stable per-node type facts, only the imports
actually used, references and required operations, and explicit runtime
obligations. Static
zero range steps, impossible zip cardinalities, unknown columns, invalid
conditions, incompatible join keys, and known column collisions fail before a
backend is selected. Data-dependent lookup cardinality, zip equality, division
denominators, finite arithmetic and series materialization, range progress, and
open-row collisions remain named obligations.
The inferred root must be assignable to its owning `ValueDef`; the root fact may
remain narrower than that consumer contract, preserving exact literal
cardinality.

`PlanExpressionSource` accepts only a verified plan and retains typed import and
used-row signatures as semantic equality facts. Semantic graph verification
therefore consumes the proof instead of repeating a weaker raw-AST scope walk,
and checks that row-dependent proofs are certified against their owning
`StateEachRegion`. Typed Program lowering re-verifies rather than reusing that
proof because inlining, scan composition, and input binding change the root and
its imports. “Sealed” here is an internal API invariant, not a same-process
security boundary; transitively immutable or fingerprinted plan storage is the
longer-term defense against private-field mutation.

Before accepting a second backend, Scopecat must specify and differentially
test ordering, duplicate preservation, null behavior, entity equality,
quantity and unit operations, numeric coercion, and join/cross/zip semantics.
Changing an evaluator must not change these observable semantics.

### Domain programs and invocation boundary

Opaque Python payloads, domain-program values, and invocations are three
different constructs. A domain-program value may declare a dialect identity
and version, codec and fingerprint, typed inputs and outputs, logical resource
requirements, and result contract. It does not require the Scopecat core to
understand the program's internal operations. Carrying such a value is not the
same as invoking it: invocation is a first-class host-visible semantic effect
with typed input, product, resource, and evidence edges.

A quantum integration therefore owns its circuit, gate, pulse, rewrite,
scheduling, feedback, and execution-control IR. Its adapter exposes a typed
program interface and a dialect compiler that can produce a target artifact.
Scopecat owns outer scans, host-side preparation and postprocessing, logical
resource, point, and product mappings, the invocation boundary, and durable
host-visible evidence. Eligible core work may enter the quantum program only
through adapter-proved target lowering. Quantum vocabulary remains outside the
core.

## Dependency Rules

The following rules are architectural constraints:

1. Authoring handles may elaborate into Module IR; no lower layer depends on
   authoring handle ownership or Python object identity.
2. Module IR may reference semantic declarations; the semantic graph does not
   depend on module instances after explicit linking.
3. The linked plan may add accepted bindings to the semantic graph; semantic
   operations do not read configuration stores or provider state.
4. Host orchestration and domain lowering consume a linked plan and declared
   implementation/target capabilities; they do not perform external effects or
   interpret domain-internal control flow.
5. Target compilers are pure. Runtime target sessions and instrument drivers
   are effectful and cannot be called by compiler passes.
6. Backend implementations depend on backend-neutral semantics, never the
   reverse.
7. Problems and source maps can describe every layer, but presentation and
   diagnostics do not participate in semantic identity.
8. Durable request, configuration, plan projections, outcomes, journal, and
   artifacts may record stable public identities and fingerprints. They do not
   serialize transient compiler graphs for replay.

## High-Level Invariants

Migration and future backend work are governed by semantic properties rather
than snapshots of IR fields:

- alpha-renaming private declarations and instances does not change observable
  products or execution intent;
- structural scopes are injective, including when individual IDs contain
  delimiter characters;
- each export preserves the identity and provenance of exactly one producer;
- linking either closes every import/reference or reports all discoverable
  blocking problems before effects;
- logical resource ports and physical resources are disjoint nominal
  namespaces even when their display strings are equal; sealing closes logical
  references, while linking or materialization validates physical identities
  against accepted configuration without name-based fallback;
- successful linking performs no relation evaluation, point materialization,
  relation-backend selection, point-local compute binding, local implementation
  selection, or point-local route/state lowering;
- every lowering preserves an operation's semantic contract exactly, and that
  contract together with its typed interface participates in the identity of
  cached compute results;
- every compute data edge references an exact `ValueId`; operation identity is
  used for implementation and invocation ownership, never as a substitute for
  a produced value, and a result-only alpha-renaming does not alter cache
  semantics;
- local implementation selection either yields one sealed artifact with exact
  compute-graph coverage or no artifact at all; candidate ordering never
  chooses a winner, and execution never reselects from a catalog;
- each target lowering either establishes exact, non-overlapping implementation
  ownership for every relation use or produces no target artifact and evaluates
  no relation; the current local lowering assigns the whole inventory to one
  backend, while linking remains reusable across target choices;
- composition order and explicit flattening do not change semantics where the
  module graph and bindings are equivalent;
- child module metadata does not implicitly merge into experiment metadata;
  the root module/template owns that entry-point projection;
- an unselected product definition survives linking but causes no acquisition
  or recording effect;
- each product use closes against exactly one definition, and each record use
  closes against exactly one product use before target lowering;
- changing record names or record-only metadata does not change product
  realization, while multiple record projections of one use do not duplicate
  target work;
- distinct product uses are not coalesced merely because their `ProductId` or
  provider key is equal; such fusion requires target-specific equivalence
  evidence;
- every successful target lowering produces each selected product use exactly
  once per logical point and maps results by nominal point/product-use
  identity, never by record name or provider key;
- value type, availability, update rate, portability, effect class, and
  placement remain independently checkable;
- different relation backends agree with the reference semantics for supported
  plans;
- point materialization, batching, offload fusion, and target result ordering
  do not change typed input/output contracts, logical point/product
  correspondence, host-visible resource/effect contracts, or observable error
  semantics;
- domain-program control flow is opaque to the generic core; a host
  orchestration plan observes only typed invocation inputs, outputs, resources,
  effects, and reconciliation evidence;
- lowering preserves effect dependencies and cannot turn an uncertain external
  effect into a safely retryable operation;
- no compiler pass requires a durable run in order to validate or lower pure
  intent.

Property-based tests should exercise these laws through public authoring,
linking, and checking boundaries. Small fixed tests may protect an individual
IR contract, but generated tests must not make an incidental record layout part
of the language semantics.

## What Remains Valid

The redesign retains these established boundaries:

- typed module inputs, exported values, available products, and template-owned
  durable record selection;
- orthogonal value shape, availability stage, and update rate;
- logical resource requirements and provider preflight before run acceptance;
- normalized run requests, accepted configuration snapshots, user-visible plan
  projections, and execution evidence as separate durable categories;
- typed apply/collect receipts, transition journals, terminal outcomes, and
  explicit uncertainty/reconciliation behavior;
- the current synchronous executor as a host-controlled local lowering and
  implementation.

## Non-Goals

This decision does not commit Scopecat to:

- immediate hardware offload or a remote execution service;
- a distributed or arbitrary multi-target scheduler;
- modeling real-time feedback, shot structure, timing, or general domain
  control flow in the Scopecat core;
- serializing every Python compute function;
- persisting compiler IR, replaying old compiler graphs, or stabilizing IR as a
  public interchange format;
- one universal plugin operation schema;
- backend-specific dataframe objects in the public DSL;
- quantum gates, circuits, pulses, or vendor concepts in the core package;
- compatibility adapters for abandoned transient IR shapes.

## Migration Sequence

Migration proceeds in semantic slices. Each slice updates affected compiler
code and tests decisively rather than maintaining parallel legacy IRs.

1. **Identity and value edges (implemented).** Introduce structural symbol identity and
   separate value declarations from uses. Preserve current public DSL behavior
   and protect it with composition properties.
2. **Explicit Module IR (implemented).** Represent interfaces, instances, bindings, and
   export projections before flattening. Make linking and flattening named,
   independently tested passes.
3. **Semantic operations and implementations (implemented for the pure value
   graph).** Separate operation meaning from Python kernels and move provenance
   into source maps. Authored Python computes and first-class scalar operations
   elaborate into `ValueDef`, `ValueUse`, and semantic operations. Local-only
   kernels remain the default implementation and enter executable records only
   during local execution lowering.
4. **Relation backend boundary (implemented through executable proof
   ownership and backend acceptance).** Relation, series,
   and scalar plans are
   data-only; centralized analysis owns traversal, references, lexical row
   scopes, and backend capabilities. Point/current/outer references are
   distinct, callback scopes use alpha-renamed nominal `RowScopeId`, row-bound
   values have an explicit row rate, and `Cross`, `LateralCross`, and internal
   `PointCross` have separate semantics. `ReferenceRelationBackend` is selected
   explicitly for host-static authoring folds. Final Typed Program verification
   seals a backend-neutral complete inventory; the current local lowering
   accepts one backend behind a whole-program capability gate before evaluation.
   Future adapter-fused lowering must provide its own exact coverage proof
   rather than weakening that gate.
   Explicit `StateEachRegion` declarations now own typed nominal row arguments
   and body `ValueUse` edges; free-row analysis excludes plan-local binders,
   and state lowering consumes the verified region graph. Typed imports,
   bidirectional per-node schema inference, runtime obligations, sealed
   `VerifiedRelationPlan`, proof-owning semantic and Typed Program envelopes,
   selected-only evaluation, prepared context dispatch, occurrence-level
   backend requirements, structured capability issues, dynamic proof-assumption
   and result normalization, sealed backend selection, and whole-program
   preflight through `VerifiedTypedProgram`/`SelectedTypedProgram` are
   implemented. A future backend supplies a policy over the existing
   occurrence-level type facts and explicitly declares the runtime obligations
   it discharges; it does not add target flags to the neutral IR. Add another
   backend only with differential semantic tests for the operations and value
   types it accepts.
5. **Symbolic point domains and linked-plan success boundary (implemented).**
   `PointDomain` preserves `Unit`, `RelationRows`, `Product`,
   `DependentProduct`, and `Zip` from authoring through Typed Program
   verification and linking. Config-free scan dependency verification supplies
   the directional composition proof. Static algebra analysis owns schemas,
   cardinality bounds, and column compatibility, while relation backends see
   only `RelationRows` leaves. `VerifiedPointDomain`, `SelectedPointDomain`,
   canonical local materialization, and nominal logical point identity are
   explicit. A successful `LinkedPlan` retains the verified relation proofs,
   complete use inventory, symbolic domain, and accepted config snapshot without
   selecting a backend. Local point materialization is a separate lowering, and
   `bind_program` merely composes linking with that lowering.
6. **Operation contracts and local selection boundary (implemented).**
   `OperationContract` retains semantic meaning, effect class, portability,
   and placement from `SemanticOperation` through `TypedComputeNode`, the
   program sealed into `LinkedPlan`, `BoundComputeCall`, and the local
   `ComputeOperation`. Semantic and Typed Program verification share intrinsic
   contract checks, while compiler verification rechecks portable scalar
   shape and types. Generic linking validates implementation sidecar identity,
   ownership, and exact contract declarations without requiring or selecting
   local Python coverage. Local materialization produces sealed, complete local
   implementation and relation-backend selections, aggregating failures before
   evaluating any relation or point; `BoundPlan` retains only target-specific
   projections and execution lowering directly consumes them. Contract and
   typed-interface fingerprints participate in compute cache keys. This slice
   adds no hardware or quantum target ABI.
7. **Nominal relation-use identity (implemented).** Every executable relation
   occurrence now owns a `RelationUseId` that contains no model path, role,
   backend, or plan fingerprint. Rewrites and point-domain payload mapping
   preserve that identity; creating another occurrence produces a fresh one,
   even when both occurrences share a verified plan. Whole-program verification
   rejects aliased identities, and selection seals exact coverage, verified
   ownership, backend consistency, proof ownership, and the point-domain bridge.
   `ModelLocation` is retained only for diagnostics. The typed carrier remains
   the owner of each use; the inventory does not yet project owners and slots
   into a separate structured union. If orchestration or domain lowering needs
   that metadata, add it beside kind and location rather than parsing
   `ModelLocation` or expanding `RelationUseId`.
8. **Nominal resource identity (implemented).** Logical resource ports retain
   structural `LogicalResourcePortId` values through authoring, sealing,
   routing, and binding, while direct and resolved hardware references retain
   `PhysicalResourceId` values. State and record targets explicitly select a
   namespace; equal display text never aliases and no pass infers a namespace
   from string equality. Sealing closes logical references, linking validates
   statically named physical references, local materialization validates
   dynamic physical references, and durable/runtime boundaries project the
   nominal values into explicitly labelled strings. Bound effects preserve
   resource kind, selected and served entities, and exact channel mappings;
   state snapshots and collection requests use the same target identity.
9. **Logical products, producer edges, uses, and record projections
   (implemented).**
   Available `ProductDef` declarations retain nominal structural `ProductId`
   values independently of nominal `InstrumentProductProducer` edges, fresh
   `ProductUse` occurrences, and template-owned `RecordUse` projections. Typed
   Program sealing closes all four inventories; `LinkedPlan` retains unselected
   definitions and producers without effects. Local lowering turns uses, not
   records, into exactly one `CollectionRequest` per point.
   A sealed local realization selection proves complete coverage before any
   relation or point is evaluated and pins the exact logical and producer
   contracts. Execution maps provider results to
   `ProductUseId` before applying one or more `RecordProjection` edges. Record
   aliases and record-only metadata therefore cannot alter or duplicate
   acquisition. Provider coordinates and transient use identities remain
   outside durable schemas. `ProductUseId` is stable only within one transient
   compilation/lowering chain, not across recompilation. A future target may
   realize the same use as a domain-program output without changing logical
   product, point, or record identity inside that chain.
10. **Explicit compute-result identity (implemented).** Typed compute nodes now
   retain an explicit result definition containing the Semantic Graph
   `ValueId`, value type, and availability. Compute edges and state result uses
   reference that value identity directly; `BoundPlan` preserves exact
   operation-to-result definitions even for zero-point plans; local execution
   stores and resolves results by `ValueId`. Operation identities continue to
   own implementation selection and dependency provenance; local lowering
   separately derives point invocation and journal identities. Graph sealing
   rejects duplicate, missing, or type-incompatible
   result edges before target work, and local selection rejects results outside
   its execute/point availability contract before relation evaluation. The
   current one-result shape remains an explicit local lowering limitation and
   does not prevent Semantic Graph IR or a future target from representing
   named multiple outputs.
11. **Host orchestration and domain invocation boundary.** Introduce one closed
   domain-program invocation only when a concrete integration needs it. Keep
   loops, branches, feedback, shots, and timing inside the domain program;
   expose only typed inputs and products, logical point mappings, resource
   claims, host-visible effects, capability evidence, and reconciliation data.
   Add adapter-proved offload fusion for specific core subplans rather than a
   generic fragment partitioner.
12. **Target runtime protocol.** Add host-visible submission, inspection, chunk
   fetch, cancellation, and reconciliation evidence in response to a real
   domain invocation ABI, not as a speculative general scheduler.

The first ten slices now form the compiler baseline. `LinkedPlan` is
target-neutral with respect to relation backend, compute meaning, and local
Python coverage, but it is not a target-selected orchestration plan. The current
local lowering owns its sealed backend and implementation selections, and
relation and product selections are keyed by nominal occurrence identity. The
product/use/record boundary now provides the result-mapping seam required by a
future domain invocation API; orchestration, offload fusion, non-local target
selections, and runtime protocol work should advance in response to a concrete
lowering and target workflow rather than speculative generic fragments.

## Consequences

The compiler gains more named passes and some apparently repetitive identities
and edge records. In return, module hygiene, backend choice, point planning,
the host/domain boundary, target selection, and runtime effects can evolve
independently. Local execution stays simple, while future offload and domain
integrations no longer require reinterpreting accidental Python or
flattened-name behavior as language semantics.

The IR remains deliberately unstable and transient. The stable commitments are
the public authoring semantics, high-level invariants, durable evidence
boundaries, and explicit target/provider contracts—not the dataclass layout of
any compiler release.
