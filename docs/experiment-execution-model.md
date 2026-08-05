# Experiment Execution Semantics

This document describes the current contract between experiment authoring,
system planning, domain compilers, and execution. It is an implementation
design, not a product requirement or roadmap. The design may be simplified
when doing so improves the current-stage workflows in the
[project charter](project-charter.md). Local rationale belongs with the types
and functions that enforce it.

## Program Boundaries

```text
@module / @experiment contexts
    | close definitions
    v
program model           shared symbolic modules, values, products, point plans
    | elaborate and verify
    v
VerifiedLogicalProgram  config-free experiment proof
    | lower, specialize, verify, and bind one accepted environment
    v
BoundPlan               verified logical program + config-bound facts
    | materialize for one experiment system
    v
RunProgram              closed residual effect program
    | interpret with effect evidence
    v
logical measurements and durable run records
```

The authoring package owns Python UX; `scopecat.program` owns definitions,
invocations, and the symbolic model consumed by compilation. The compiler does
not import authoring modules. `BoundProgramFacts` is transient compiler data,
not a versioned interchange format.
`RunProgram` is the executable representation for one accepted run; physical
batching does not change its logical points, product identities, or results.

## Authoring and Ownership

A reusable module combines a pure typed graph with an ordered sequence of
consequential effects. The sequence may contain desired state, acquisitions,
domain executions, and child-module occurrences.
Composing a child scopes its resource, value, product, and effect identities to
that instance and places its effects exactly once.
Domain-program calls are distinct occurrences: each call owns its result
products and is placed directly in the ordered effects. A child module is
needed only when those effects are deliberately composed into a larger reusable
workflow.

The public authoring model follows four rules:

1. `@module` defines a reusable graph fragment. Its Python return value is its
   sole composition result. `context.use(module(...))` places the invocation's
   effects and returns that typed result directly at either authoring boundary.
   Domain calls likewise return their owned result products from `use(...)`.
   There is no second user-authored output or product-export declaration.
2. `@experiment` authors a complete experiment. Parameters annotated as
   `Input[T]` are typed runtime inputs and may have definition defaults; plain
   Python parameters are structural values that rebuild the graph for that
   invocation. An experiment may coordinate any number of local devices,
   reusable modules, and domain calls.
3. A domain call is one effect in that experiment, not the experiment boundary.
   A lab-owned runner may add compiler inputs, auxiliary-device work,
   postprocessing, and recording without requiring a wrapper module. Hardware
   that must vary synchronously inside each domain point belongs to that
   target/compiler contract.
4. `record(...)` is the single dataset projection. It accepts symbolic scalar
   values, product references, typed product bundles, and per-entity mappings.
   Values remain dataflow nodes and products remain measurement/evidence nodes;
   demanded record roots determine the live compute and postprocessor DAG, whose
   dependencies determine execution order.

### Point plans and invocation edits

Every experiment resolves to one `PointPlan`: one domain, one repeat policy,
and one traversal policy. The authoring rules are deliberately small:

1. Repeated `experiment.scan(...)` calls infer typed coordinates and accumulate
   one Cartesian product. `experiment.grid(...)` declares that product
   explicitly; `experiment.points(...)` declares explicit ordered rows. The
   inferred and explicit forms cannot be mixed. No declaration means the unit
   grid with one point; an empty point cloud has zero points.
2. Calling the decorated experiment with plain Python arguments rebuilds its
   structural graph. `Input[T]` arguments are runtime values; invocation
   `.bind(...)` and `.unbind(...)` only edit those values.
3. Invocation `.grid(...)` and `.points(...)` replace the domain.
   `.with_axis(...)` and `.without_axis(...)` edit only a grid;
   `.with_repeat(count, mode=...)` and `.with_traversal(...)` edit their
   independent policies. `.reset_points()` discards the whole invocation
   point-plan override. Explicit points always use their row order, so replacing
   a snake grid with `.points(...)` restores forward traversal.
4. A repeat count greater than one adds the canonical `repeat` coordinate.
   `mode="point"` keeps repeats of one base point adjacent; `mode="sweep"`
   keeps complete sweeps adjacent. `traversal="snake"` changes only physical
   product-grid execution order. Logical point ids, dataset point indices, and
   durable measurement rows stay in canonical order.

Use explicit point rows for correlated, sparse, filtered, duplicated, or
deterministically shuffled work. Use a staged experiment when the next point
depends on an earlier measurement. There is no second filtering, randomization,
or adaptive-loop DSL hidden inside a point plan.

Logical resource ports and interface requirements form the reusable boundary
between a module and the physical configuration selected for a run. Authoring
never names an instrument or channel. It may select logical entities from
accepted inputs, parameters, or point coordinates; the accepted configuration
alone owns their finite physical endpoint mapping.

### Completion and failure state

`experiment.on_success(client, state)` declares a fixed state applied after
the experiment's effects and point coverage complete without failure,
indeterminate outcome, or interruption. It is a normal-completion operation,
not an unconditional cleanup hook; final dataset sealing and the durable
terminal commit may still occur afterward.

The runtime state names describe different facts. `observed_state` is the
initial readback after exclusive acquisition; `prepared_state` is the baseline
after run-start policy. Authored `on_success` state is then applied only after
coverage succeeds. Each accepted instrument then applies its configured
`success_action`: `release` leaves that successful state in place, while
`restore_prepared_state` restores the writable portion of its prepared baseline.
Runtime `final_state` is terminal readback evidence gathered after that action
and before release. It is not an authored target, does not prove the run
succeeded, and may be empty or incomplete when restoration or terminal readback
fails.

The successful order is therefore authored `on_success`, configured success
action, terminal readback, and release. A rejected prepared-state restoration
turns the run into a failure and enters the configured abort/safe-state path. An
unknown restoration outcome is indeterminate and quarantines the affected
hardware just like any other unknown hardware effect.

Failure cleanup belongs at the layer that can still command the hardware:

- the instrument driver owns `abort()` and is the only cleanup attempted after
  an unknown hardware outcome;
- accepted instrument configuration may select `abort_then_safe_state` to add
  a sparse safe state after abort while the device remains commandable;
- the current domain runtime ABI exposes only `submit` and `fetch`, not a
  core-driven terminate hook. An operator cancellation can stop before or after
  a domain job, but it cannot interrupt that job in the middle. A target that
  requires active termination must contain it inside its runtime contract;
  otherwise Scopecat cannot promise domain cleanup. A generic domain
  terminate/progress ABI remains deferred until a concrete asynchronous target
  demonstrates the contract it needs.

Operator cancellation is a durable control-plane request, not an authored
cleanup callback. Queued runs close immediately; leased runs observe the request
through executor heartbeats and stop at the next operation, hardware-batch,
coverage, or normal-completion boundary. Known cancellation still enters the
configured abort/safe-state path. If that finalization is unknown, the run is
cancelled with indeterminate certainty and its resources remain quarantined.
The durable request and terminal commit are serialized: a request that wins the
race converts only a pending successful intent to cancelled, while an actual
failed or indeterminate intent keeps its stronger evidence.

Authoring deliberately exposes no arbitrary Python `finally` callback or
promised-always state. Workflows that require stronger cleanup must first move
that intent to daemon ownership before the first hardware effect.

Product declaration, acquisition, and recording are distinct:

1. A module or native domain call declares the identity and shape of products
   it can make.
2. An acquisition places instrument realization at an exact effect position
   and names one logical port, one versioned interface, one acquisition, and
   its result ids.
3. An experiment selects products and values that become records.

Products created by domain execution or pure transforms retain those explicit
producers and do not create instrument acquisitions. Provider acquisition
result resolution never searches globally for a coincidentally unique result
id.

A domain program owns opaque dialect data with typed inputs and result products.
Scopecat owns the surrounding identities, typed bindings, effect order, and
result correlation; the accepted system configuration owns the domain target's
physical footprint. Experiments own invocation policy: input defaults, point
plans, durable record selection, labels, and metadata.

After a target acknowledges submission, an exception while fetching does not
establish whether the asynchronous job is still active, completed, or otherwise
changed; the run is therefore indeterminate. A structured provider `not_found`
receipt is known evidence, while a provider `unknown` receipt remains
indeterminate.

## Semantic Invariants

- A run uses an accepted request and an identifiable configuration snapshot.
- One `ExperimentSystem` owns one domain compiler; routing among supported
  domain programs and physical targets is internal to that compiler.
- Logical entity selection may vary by point; physical endpoint ownership may
  vary only through the finite mapping in that snapshot.
- Every physical selection is deterministic and retained in execution
  provenance; provider failure never triggers implicit failover.
- Logical point identity and coordinates are independent of physical batching.
- Point parameter overrides agree across host and domain placement.
- Pure computation may be folded, shared, hoisted, or placed on a domain target
  without changing its value.
- Consequential effects retain declared order. State, acquisitions, and domain
  jobs cannot be moved across an observable ordering boundary.
- Domain jobs remain inside barriers created by varying inputs, conflicting
  resources, and observable effects.
- Legal host/domain lowering and legal physical partitioning produce the same
  demanded logical products.
- Every physical result maps completely and unambiguously to logical points and
  product-use identities.
- Intent is recorded before consequential external invocation.
- An unknown effect outcome is never silently retried.
- Check, preview, and run specialize the same accepted semantics; check and
  preview perform no provider effects.
- Abort, disconnect, and terminal outcome derivation remain explicit.

Tests should assert these laws instead of transient compiler fields, cache
behavior, or incidental batch counts.

## Symbolic Specialization

Point composition remains symbolic through verification and specialization.
Linking materializes one ordered point sequence; host lowering, parameter
overlays, entity selection, and domain projection consume those same point rows.

Partial evaluation binds accepted inputs and configuration values, applies the
invocation's point-plan override, folds pure subgraphs, removes undemanded work,
and leaves residual host and domain computation. It is pure: reads, state
mutation, acquisitions, low-level driver actions, and other external effects
execute only from a `RunProgram`. Any concrete fallback is bounded by an
explicit materialization limit.

A parameter overlay is one specialization path: `parameter_lookup` selects a
cell from the accepted snapshot, and `axis(..., overlay=lookup)` supplies its
point-local value. Host and domain placement observe the same overlaid value.

Activating an approved proposal selects a new immutable snapshot for later
specialization; it does not introduce another compiler or configuration path.

## Domain Lowering

An experiment definition is independent of the `ExperimentSystem` that runs
it. The accepted system configuration statically selects one domain target and
its complete physical footprint. Planning verifies the configured compiler's
target identity once, and the run claims that footprint once. The compiler
participates through one `compile_batch` boundary. Planning first partitions
the logical point space by the compiler's declared capacity, then resolves all
program and compiler inputs for each execution-ordered bounded batch.
`compile_batch` closes
the target artifact, exact point/product mapping, runtime invocation, and
result realization into one prepared execution.

A domain program has two typed input namespaces. Program inputs are part of
its runtime semantics. Compiler inputs configure lowering itself. Both are
resolved from the same snapshot-plus-overlay parameter model before the domain
compiler is called. This lets experiments vary compiler parameter collections
by point without disguising them as a small set of program arguments or
injecting mutable compiler state.

A domain compiler may call a lower-level target compiler after inputs have been
resolved and a program has been lowered to target IR. That is an internal
lowering stage, not another compiler selected on the `ExperimentSystem`.

## Effects and Physical Resources

Provider instruments are provisioned for the run. Physical binding is a pure
projection of the accepted snapshot: it does not inspect live availability,
choose by load or cost, or fail over after execution starts. A point-local
entity coordinate may select different configured endpoints, but it cannot
construct a new physical route.

Desired state may be split by static entity ownership so different instruments
maintain explicit values for their devices. A single low-level action or
acquisition is one driver invocation and is never implicitly broadcast across
instruments. Each concrete effect carries only the endpoint bindings for its
own explicit interface.

Switch matrices, patch panels, valves, probers, and similar path-changing
devices are explicit desired-state or domain effects. Selecting replacement
hardware requires another accepted configuration and plan so the physical
choice stays reproducible.

Planning materializes every coverage block before admission, then derives one
flat run-level claim set from the concrete effects: the configured domain target
and its independently addressable instrument members, plus each instrument
actually used by residual host operations. Target-private endpoints are
connections owned exclusively by the target backend; they are not advertised as
instruments and are covered by the target claim. The target claim uses a stable
configuration-owned exclusivity key rather than the logical target id, and
admission authorizes the complete member binding before resolving that key.
This lets a composite target mix shared lab instruments with hardware that has
no meaningful standalone contract without inventing an operator-facing device
API. The flat claim set is leased once across provider provisioning and the
whole effect program. Channel and topology-group bindings remain exact command
data; the scheduler does not pretend they form a hierarchical lease model.
Compatibility that depends on values or simultaneous hardware operation
belongs to the provider or domain compiler.

## Execution, Outcomes, and Measurements

Execution consumes bounded coverage once, records intent before invoking an
external effect, and may commit completed measurement prefixes at checkpoints.
Consequential effects distinguish:

- **completed**: the effect occurred and returned validated evidence;
- **rejected**: it is known not to have occurred; and
- **unknown**: it may have occurred.

Unknown outcomes stop dependent execution because automatic retry could repeat
an external effect. Abort and actor connection retirement remain explicit
lifecycle steps.

Host collection and domain execution produce one logical measurement stream.
Physical chunks and target locations do not alter result identity. One physical
result may feed multiple uses of the same product, conflicting values for one
use are rejected, and exact demanded coverage is verified before results enter
the canonical stream. Durable evidence, rather than UI events or metrics, is
the source of truth for operator reconciliation and final run status.
