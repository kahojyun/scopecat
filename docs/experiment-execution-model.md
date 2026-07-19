# Experiment Compilation and Execution Target

This document defines the target compilation and execution model for Scopecat
experiments. It is a direction-setting contract, not a description of the
current implementation.

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

The initial implementation of this target is complete. `CoreProgram` owns one
ordered effect sequence, and `RunProgram` owns one ordered operation sequence
interpreted by the run effect interpreter. Normal execution does not construct
the former bound-plan, local-program, prepared-plan, segment, lane, fusion,
coverage-reconstruction, execution-cache, or measurement-fragment models.

Point composition remains symbolic through verification and specialization.
The synchronous initial runtime closes the accepted run's logical point and
result mappings during `RunProgram` compilation under an explicit
`max_materialized_points` budget. Domain compilers receive the verified
symbolic point domain, specialized residual inputs, barrier regions, and a
budgeted point-binding API; they may absorb scan axes and declare a
dependency-closed prefix of portable result transforms as pushed down.
Unsupported inputs and transforms remain residual host work.

Config-bound host data used during specialization is temporary compiler data,
not an executable plan. Host lowering writes the final `RunLocalEffects`
operation directly, and domain lowering writes `RunDomainJob` operations with
exact logical-point and product correlation. Canonical measurement candidates
from both placements are sealed once at the run boundary.

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

The core provides a domain compiler with:

- the typed domain body and ports;
- specialized residual input expressions;
- the relevant symbolic point-space region;
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

Compiler selection should be explicit from a domain dialect/version and target
capabilities. It should not rely on adapters behaviorally probing a fully
materialized point batch.

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
same measurement through several fragment forms.

Artifacts, datasets, and records should share one content-index model with an
explicit role, content digest, media type, and schema where applicable.
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
- host execution and valid domain pushdown produce identical logical points and
  demanded products;
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

## Migration Sequence

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

The migration is complete only when normal execution no longer constructs or
adapts the old plan and engine models.
