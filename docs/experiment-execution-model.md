# Experiment Execution Semantics

This document records the lasting semantic contract between Scopecat's
experiment compiler, experiment-system planning, domain compilers, and the run
interpreter. It intentionally does not inventory compiler passes, current
helper types, or completed migrations. Those implementation details belong in
the code and may change without changing this contract.

## Program Boundaries

Scopecat has two meaningful compiler representations:

```text
authoring model
    | elaborate, type-check, and verify
    v
CoreProgram             typed, symbolic experiment meaning
    | link, specialize, and lower for one experiment system
    v
RunProgram              closed residual effect program
    | interpret synchronously with effect evidence
    v
canonical logical measurements and run records
```

`CoreProgram` retains symbolic point composition, typed values, pure compute,
ordered effects, product ownership, and result demand. It is transient compiler
data, not a durable or versioned interchange format.

`RunProgram` is the sole executable representation. It combines run-invariant
host compute with a single-use source of bounded coverage blocks. A block
contains already-bound host effects, prepared-on-demand domain jobs, exact
logical coverage, resource claims, and measurement checkpoints. The runtime
does not reconstruct host and domain lanes or another point program.

Specialization may use temporary analyses and builders. They should establish
one local invariant or directly construct one of these two programs, rather
than becoming another public plan hierarchy.

## Semantic Invariants

The implementation must preserve these user-visible laws:

- A run uses an accepted request and an identifiable configuration snapshot.
- Every logical point has stable identity and coordinates independent of
  physical batching, coverage block size, or target lowering.
- A parameter override at a point is observed consistently by host and domain
  computations at that point.
- Pure computations may be folded, hoisted, shared, or pushed into a domain
  target without changing their values.
- Consequential effects retain declared order unless an accepted compiler
  proof permits reordering.
- A domain job cannot cross an effect barrier that may change one of its
  inputs, conflicting resources, or observable results.
- Every demanded product has one complete, unambiguous mapping from physical
  results to logical points and product-use identities.
- Intent is recorded before invoking a consequential external effect.
- An effect whose outcome is uncertain is not silently retried.
- Abort, cleanup, and terminal outcome derivation remain explicit.

The following are not semantic contracts:

- compiler pass names or counts;
- internal plan, wrapper, artifact, or fragment shapes;
- physical job counts, batch boundaries, or coverage block size;
- whether point-invariant pure work was hoisted;
- cache keys, hit counts, or status events; and
- host-versus-domain placement when both preserve the laws above.

Tests should prefer these laws over snapshots of transient IR structure.

## Symbolic Points and Partial Evaluation

Point composition remains symbolic through verification and specialization.
The compiler owns one iteration layout that preserves the structure it can
prove: ordered product and zip nesting, dependent boundaries, exact finite
axes and their strides, and opaque regions. Consumers may project this layout;
they must not reconstruct a second scan model from materialized rows.

Partial evaluation is normal compilation semantics, not an optional runtime
optimization. It binds accepted invocation inputs and configuration values,
applies lexical scan overrides, folds pure subgraphs, removes undemanded work,
and exposes a smaller residual graph to host and domain lowering.

Three facts remain separate:

- whether a pure expression is known from the request or configuration;
- which point columns, parameters, or routes make a residual object vary; and
- whether an object is consequential external work.

They must not be collapsed into a global stage or rate lattice. Residual pure
compute needs only run and point evaluation scopes, derived from transitive
dependencies. More precise reuse coverage is derived from the compiler-owned
iteration layout and variation support.

Partial evaluation must never perform a live read, state mutation, action,
acquisition, or other external effect. Any bounded fallback that concretizes
points or inputs must have an explicit materialization limit.

## Experiment-System and Domain Lowering

An experiment definition is independent of the experiment system that runs it.
One `ExperimentSystem` supplies the physical host provider and, when needed,
one domain compiler. Routing among target dialects, versions, and capabilities
belongs inside that system compiler, not in a core plugin competition model.

The experiment-system planner is the only `CoreProgram` to `RunProgram`
boundary. It selects local implementations, closes the accepted logical point
catalog, derives resource and ordering barriers, and creates a bounded
single-use coverage source. Host-only, domain-only, and mixed experiments use
the same program and interpreter path.

A domain compiler participates in specialization under three boundaries:

1. `claim_resources` declares the target footprint needed to form legal
   barriers before compilation.
2. `compile` performs pure, bounded target lowering over symbolic inputs and
   exact logical ordinal regions.
3. `prepare` binds one selected job to its runtime context and produces the
   single-use invocation consumed by execution.

Compilation may absorb constants, finite axes, portable pure computation, and
supported result transforms. It may choose target-native loops, tables,
waveforms, artifact sharing, job partitions, and physical execution order.
Unsupported work remains residual host work.

A domain compiler must not:

- change logical point identity, coordinates, or lexical parameter semantics;
- inspect or execute live reads, actions, receipts, or state mutation;
- cross an ordering or conflicting-resource barrier;
- evaluate opaque host code;
- claim an input or transform it did not actually absorb; or
- return a result without complete logical correlation.

The SDK exposes an owned projection of symbolic inputs and iteration layout,
not the compiler's internal AST. Exact normal forms are an opportunity for
target lowering; opaque values use a bounded concrete binder. Absorption claims
and binder provenance are immutable compilation output, while residual sets are
their derived complements rather than parallel ownership models.

Physical batching is therefore an ordinary target-lowering decision, not a
separate fusion phase. A one-point target is represented by a capacity limit,
not another engine path.

## Effects, Resources, and Coverage

`CoreProgram` owns one declared effect sequence. Planning retains those effect
slots while lowering state, actions, host collection, and domain calls. Actions
are hard ordering boundaries. State changes split a domain region only when
their resource claims conflict with the compiler's declared target footprint.

Resource ownership has two lifetimes:

- provider instruments are provisioned and leased for the run; and
- point routes, channels, shared groups, and domain target claims are leased
  only for the coverage block that uses them.

Claims already held by the run lease are not reacquired by a block. Barrier
construction uses authoritative pre-compilation claims rather than inspecting
a compiled artifact or prepared payload.

The initial runtime is synchronous. It consumes each coverage block exactly
once, admits its contiguous logical point range, executes operations in program
order, commits completed measurement prefixes at explicit checkpoints, and
releases block-local candidates and resources before requesting the next block.

Consequential host and domain effects follow the same safety distinction:

- **completed**: the effect occurred and returned validated evidence;
- **rejected**: the effect is known not to have occurred; or
- **unknown**: the effect may have occurred.

Unknown stops dependent execution and is never automatically retried. The
interpreter records observed facts; the run boundary derives terminal result,
certainty, and termination reason once.

## Measurements and Observability

Host collection and domain execution produce the same logical measurement
candidate stream. Candidates are closed against the admitted points and final
product-use catalog, transformed, projected, and appended once per completed
coverage. Physical target locations and chunks do not become a second logical
result hierarchy.

One target result location may feed multiple uses of the same logical product.
Distinct locations may not silently provide conflicting values for one use.
Exact demanded output coverage is validated before results enter the canonical
measurement stream.

Measurement arrays are ordinary transient in-memory values. Incremental
coverage lets downstream processing release them when no longer needed; the
model does not require external array references or engine-owned reference
counting. Peak-memory improvements may be added later without changing logical
measurement identity or coverage semantics.

Durable evidence records intent and outcome transitions needed for safety and
recovery. UI events, metrics, and diagnostics are projections of the same
observed trace, not additional execution contracts. Successful terminal
publication uses committed append and seal evidence without reloading the
measurement repository.

## Deliberate Non-goals

The current contract deliberately excludes:

- adaptive or measurement-guided point admission;
- a separate optimization run type;
- asynchronous suspension, restart, or resumable job orchestration;
- external measurement-array handles and engine reference counting;
- cross-run compiled-artifact cache semantics; and
- compatibility with removed engine stages, lanes, fusion, fragments, or plan
  wrappers.

These features may be designed later. They must extend the semantic boundaries
above explicitly rather than hide new lifecycles behind the synchronous API.

## Verification Laws

High-value tests establish that:

- partial evaluation preserves logical values;
- scan overrides are identical in host and domain placement;
- valid host and domain lowerings produce the same demanded products;
- different legal physical partitions produce the same logical results;
- domain jobs remain inside ordering and conflicting-resource barriers;
- every physical result maps exactly to demanded logical outputs;
- intent precedes each consequential external invocation;
- rejected and unknown outcomes have distinct retry semantics;
- abort and cleanup retain their documented order; and
- check, preview, and run specialize the same accepted program without check or
  preview performing provider effects.

Exact internal operation sequences are tested only when the sequence is itself
part of one of these contracts.
