# Experiment Execution Semantics

This document records the stable contract between experiment authoring, system
planning, domain compilers, and execution. Implementation details and local
design rationale live with the types that enforce them.

## Program Boundaries

```text
authoring model
    | elaborate, type-check, and verify
    v
CoreProgram             typed, symbolic experiment meaning
    | link, specialize, and lower for one experiment system
    v
RunProgram              closed residual effect program
    | interpret with effect evidence
    v
logical measurements and durable run records
```

`CoreProgram` retains symbolic point composition, typed values, pure compute,
ordered effects, product ownership, and result demand. It is transient compiler
data, not a versioned interchange format.

`RunProgram` is the executable representation. It combines run-invariant host
compute with a bounded, single-use source of coverage blocks. Each block
contains bound host effects, prepared-on-demand domain jobs, exact logical
coverage, resource claims, and measurement checkpoints.

## Authoring Composition

A reusable module owns:

- a pure typed graph of inputs, computations, values, product declarations,
  and product transforms; and
- an ordered procedure of consequential effects, with explicit groups that may
  be scheduled in parallel.

The procedure may contain desired-state bindings, row-scoped state, instrument
actions, acquisitions, domain executions, and child-module occurrences.
Composing a child scopes its resource, value, product, and effect identities to
that instance and places its procedure exactly once. Pure declarations do not
create procedure positions.

Logical resource ports and capability requirements form the reusable boundary
between a module and the physical configuration chosen for a run. Child
resources bind explicitly to parent resources. `sequence` fixes procedure
order; `parallel` grants scheduling permission when concrete resource claims
are compatible.

Product declaration, acquisition, and durable recording are separate:

1. A module declares the identity, shape, and producer mapping of products it
   can make.
2. An acquisition places their realization at an exact procedure position.
3. A template or scratch experiment selects product uses that become records.

Every selected instrument product is acquired once per logical point. Products
created by domain execution or pure transforms retain their own producer and do
not create instrument acquisitions.

A domain program definition contains reusable, opaque dialect data with typed
inputs, result products, and logical resource roles. Binding that definition
creates a module-owned domain effect. The dialect owns internal operations;
Scopecat owns stable identity, typed bindings, capability requirements,
ordering, resource correlation, and result correlation.

Templates own invocation policy: defaults, scans, durable record selection,
labels, and metadata. Effects and domain executions stay in modules. A
pure-compute-only module, an effect-only module, and a module combining both are
all valid composition units.

The highest-value reuse boundaries are:

1. device parameter and desired-state mappings;
2. repeated configure, arm, wait, trigger, acquire, and readout procedures,
   including safe parallelism;
3. domain-program input, result, and resource-role mappings; and
4. experiment-specific domain bodies, scans, defaults, and record choices.

The first three normally belong in reusable modules. The last group belongs in
a concrete experiment module and its template.

## Semantic Invariants

- A run uses an accepted request and an identifiable configuration snapshot.
- Logical point identity and coordinates are independent of physical batching.
- A point parameter override is identical in host and domain computation.
- Pure computation may be folded, shared, hoisted, or placed on a domain target
  without changing its value.
- Consequential effects retain declared order unless an accepted proof permits
  reordering.
- Domain jobs remain inside barriers created by their varying inputs, resource
  conflicts, and observable effects.
- Every demanded product maps completely and unambiguously from physical
  results to logical points and product-use identities.
- Intent is recorded before a consequential external invocation.
- An uncertain effect outcome is never silently retried.
- Abort, cleanup, and terminal outcome derivation remain explicit.

Tests should assert these laws instead of transient compiler structure, batch
counts, cache behavior, or host-versus-domain placement.

## Symbolic Points and Partial Evaluation

Point composition remains symbolic through verification and specialization.
One compiler-owned iteration layout preserves ordered product and zip nesting,
dependent boundaries, finite axes and strides, and opaque regions. Consumers
project that layout rather than reconstructing point structure from rows.

Partial evaluation binds accepted inputs and configuration values, applies
lexical scan overrides, folds pure subgraphs, removes undemanded work, and
leaves residual host and domain computation. Variation is derived from
transitive dependencies and the iteration layout.

Partial evaluation is pure: live reads, state mutation, actions, acquisitions,
and other external effects execute only from a `RunProgram`. Any concrete
fallback for symbolic inputs is bounded by an explicit materialization limit.

## Experiment-System and Domain Lowering

An experiment definition is independent of the `ExperimentSystem` that runs
it. The system selects physical providers and the applicable domain compiler,
then specializes one `CoreProgram` into one `RunProgram` path for host-only,
domain-only, or mixed execution.

A domain compiler participates through three boundaries:

1. `claim_resources` declares the target footprint used to form legal barriers.
2. `compile` performs pure, bounded lowering over symbolic inputs and exact
   logical ordinal regions.
3. `prepare` binds a selected job to runtime context and returns its single-use
   invocation.

Compilation may absorb constants, finite axes, portable pure computation, and
supported product transforms. It may choose target-native loops, tables,
waveforms, shared artifacts, job partitions, and physical order. Unsupported
work remains residual host work.

Lowering preserves logical points, lexical parameters, effect barriers, and
complete result correlation. It only claims inputs and transforms actually
absorbed by the target. The SDK exposes an owned projection of symbolic inputs
and iteration layout; opaque values use a bounded concrete binder.

## Effects, Resources, and Coverage

`CoreProgram.effects` is the authoritative order. Parallel groups record
authored scheduling permission over that sequence. Planning retains those
positions while lowering state, actions, acquisitions, and domain executions.
Actions and acquisitions are ordering barriers; state changes create a barrier
when their claims conflict with a domain target footprint.

Provider instruments are provisioned for the run. Point routes, channels,
shared groups, and domain claims are leased for the coverage block that uses
them. Barrier construction uses resource claims declared before compilation.

The interpreter consumes every coverage block once, admits its contiguous
logical point range, executes operations in order, commits completed
measurement prefixes at checkpoints, and releases block-local resources before
requesting the next block.

Consequential effects have three outcomes:

- **completed**: the effect occurred and returned validated evidence;
- **rejected**: the effect is known not to have occurred; or
- **unknown**: the effect may have occurred.

An unknown outcome stops dependent execution. The run boundary derives final
status, certainty, and termination reason from the recorded evidence.

## Measurements and Observability

Host collection and domain execution produce one logical measurement candidate
stream. Candidates are checked against admitted points and product-use demand,
transformed, projected, and appended once per completed coverage. Physical
chunks and target locations do not alter logical result identity.

One physical result may feed multiple uses of the same product. Conflicting
values for one use are rejected, and exact demanded coverage is verified before
results enter the canonical stream.

Durable evidence records intent and outcome transitions needed for safety and
recovery. UI events, metrics, and diagnostics are projections of that trace.

## Verification Laws

High-value verification establishes that:

- partial evaluation preserves logical values;
- scan overrides agree across host and domain placement;
- legal host and domain lowerings produce the same demanded products;
- legal physical partitions produce the same logical results;
- domain jobs remain inside ordering and resource barriers;
- every physical result maps exactly to demanded logical outputs;
- intent precedes every consequential external invocation;
- rejected and unknown outcomes have distinct retry semantics;
- abort and cleanup retain their documented order; and
- check, preview, and run specialize the same accepted program while check and
  preview perform no provider effects.
