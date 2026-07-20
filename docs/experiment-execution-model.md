# Experiment Execution Semantics

This document records the stable contract between experiment authoring, system
planning, domain compilers, and execution. Local design rationale belongs with
the types and functions that enforce it.

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

`CoreProgram` is transient compiler data, not a versioned interchange format.
`RunProgram` is the executable representation for one accepted run; physical
batching does not change its logical points, product identities, or results.

## Authoring and Ownership

A reusable module combines a pure typed graph with an ordered procedure of
consequential effects. The procedure may contain desired state, instrument
actions, acquisitions, domain executions, and child-module occurrences.
Composing a child scopes its resource, value, product, and effect identities to
that instance and places its procedure exactly once.

Logical resource ports and capability requirements form the reusable boundary
between a module and the physical configuration selected for a run. Authoring
never names an instrument or channel. It may select logical entities from
accepted inputs, parameters, or point coordinates; the accepted configuration
alone owns their finite physical endpoint mapping.

Product declaration, acquisition, and recording are distinct:

1. A module declares the identity and shape of products it can make.
2. An acquisition places instrument realization at an exact procedure position
   and names one logical port, one explicit capability, and provider product
   keys.
3. A template or scratch experiment selects product uses that become records.

Products created by domain execution or pure transforms retain those explicit
producers and do not create instrument acquisitions. Provider product lookup
never searches globally for a unique capability or product key.

A domain program owns opaque dialect data with typed inputs, result products,
and logical resource roles. Scopecat owns the surrounding identities, typed
bindings, capability requirements, effect order, resource correlation, and
result correlation. Templates own invocation policy: defaults, scans, durable
record selection, labels, and metadata.

## Semantic Invariants

- A run uses an accepted request and an identifiable configuration snapshot.
- Logical entity selection may vary by point; physical endpoint ownership may
  vary only through the finite mapping in that snapshot.
- Every physical selection is deterministic and retained in execution
  provenance; provider failure never triggers implicit failover.
- Logical point identity and coordinates are independent of physical batching.
- Point parameter overrides agree across host and domain placement.
- Pure computation may be folded, shared, hoisted, or placed on a domain target
  without changing its value.
- Consequential effects retain declared order. State, actions, acquisitions,
  and domain jobs cannot be moved across an observable ordering boundary.
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
- Abort, cleanup, and terminal outcome derivation remain explicit.

Tests should assert these laws instead of transient compiler fields, cache
behavior, or incidental batch counts.

## Symbolic Specialization

Point composition remains symbolic through verification and specialization.
One compiler-owned iteration model is shared by host lowering, parameter
overlays, entity selection, and domain projection so consumers cannot disagree
about point variation or nesting.

Partial evaluation binds accepted inputs and configuration values, applies
lexical scan overrides, folds pure subgraphs, removes undemanded work, and
leaves residual host and domain computation. It is pure: reads, state mutation,
actions, acquisitions, and other external effects execute only from a
`RunProgram`. Any concrete fallback is bounded by an explicit materialization
limit.

## Domain Lowering

An experiment definition is independent of the `ExperimentSystem` that runs
it. A domain compiler participates through three boundaries:

1. `claim_resources` declares the target footprint used to form legal barriers.
2. `compile` performs pure, bounded lowering over symbolic inputs and exact
   logical coverage.
3. `prepare` binds one selected job to runtime context and returns its
   single-use invocation.

Compilation may absorb supported constants, finite axes, pure computation, and
product transforms. Unsupported work remains residual host work. Lowering must
preserve logical points, lexical parameters, effect barriers, and complete
result correlation, and may claim only work actually absorbed by the target.

## Effects and Physical Resources

Provider instruments are provisioned for the run. Physical binding is a pure
projection of the accepted snapshot: it does not inspect live availability,
choose by load or cost, or fail over after execution starts. A point-local
entity scan may select different configured endpoints, but it cannot construct
a new physical route.

Desired state may be split by static entity ownership so different instruments
maintain explicit values for their devices. A single action or acquisition is
one driver invocation and is never implicitly broadcast across instruments.
Each concrete effect carries only the endpoint bindings for its own explicit
capability.

Switch matrices, patch panels, valves, probers, and similar path-changing
devices are explicit state or action effects. Selecting replacement hardware
requires another accepted configuration and plan so the physical choice stays
reproducible.

Exact instrument, channel, and topology-group claims are derived only after
entity binding. Their enclosing run, coverage block, or domain job defines the
lease lifetime. Compatibility that depends on values or simultaneous hardware
operation belongs to the provider or domain compiler rather than generic
channel-count rules.

## Execution, Outcomes, and Measurements

Execution consumes bounded coverage once, records intent before invoking an
external effect, and may commit completed measurement prefixes at checkpoints.
Consequential effects distinguish:

- **completed**: the effect occurred and returned validated evidence;
- **rejected**: it is known not to have occurred; and
- **unknown**: it may have occurred.

Unknown outcomes stop dependent execution because automatic retry could repeat
an external effect. Abort and cleanup remain explicit evidence-bearing steps.

Host collection and domain execution produce one logical measurement stream.
Physical chunks and target locations do not alter result identity. One physical
result may feed multiple uses of the same product, conflicting values for one
use are rejected, and exact demanded coverage is verified before results enter
the canonical stream. Durable evidence, rather than UI events or metrics, is
the source of truth for recovery and final run status.
