# Scopecat Quantum

Hardware-independent quantum building blocks for Scopecat.

The package provides logical gates, mixed gate-and-pulse programs,
implementation binding, and the checked target-compiler boundary. Laboratory
experiment definitions, parameters, wiring, artifacts, runtimes, and response
models remain in the integrating project.

The package root exports the `authoring` facade. Target integrations import
their contracts from the owning submodules so those boundaries stay explicit.

```python
from typing import Annotated

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum import authoring
from scopecat_quantum.gates import GateParameterKind

x90 = authoring.single_qubit_gate("x90")
beta_type = sc.ScalarType(sc.QuantityType(unit="ns"))


@authoring.implementation(of=x90, candidate="x90.drag")
def x90_drag(
    qubit: authoring.Qubit,
    beta: Annotated[Quantity, beta_type],
) -> authoring.QuantumFragment:
    return authoring.play(
        authoring.drive(qubit),
        authoring.drag(
            duration=Quantity(16, "ns"),
            amplitude=Quantity(0.2, "arb"),
            sigma=Quantity(4, "ns"),
            beta=beta,
        ),
    )


@authoring.program(id="x90-count")
def x90_count(
    qubit: authoring.Qubit,
    beta: Annotated[Quantity, beta_type],
    count: Annotated[int, GateParameterKind.INTEGER],
) -> authoring.QuantumFragment:
    return authoring.repeat(x90_drag(qubit, beta=beta), count)


call = x90_count(
    qubit="q0",
    beta=Quantity(0.75, "ns"),
    count=3,
).with_shots(32)
```

Program inputs may bind directly to Scopecat values such as
`scopecat.parameter_lookup(...)`. A `Program` call is a native domain
occurrence that owns its effect, execution options, and named result products.
Place it with `context.use(call)` inside either `@sc.module` or
`@sc.experiment`. A lab can own a fixed experiment that
injects compiler inputs, measurement measurement computing, recording policy, and
independent auxiliary-device work; the program call remains one domain effect
rather than becoming the whole experiment. The
[reference lab runner](../../examples/reference_lab/README.md) shows that path.

Variable-size programs use a retained `QubitSet` port and `parallel_each`:

```python
@authoring.program(id="parallel-readout")
def parallel_readout(
    qubits: authoring.QubitSet,
) -> authoring.QuantumFragment:
    return authoring.parallel_each(
        qubits,
        lambda qubit: authoring.measure(qubit, result="iq_shots"),
    )


call = parallel_readout(
    authoring.select_qubits(
        3,
        connected=True,
        anchor="q1",
        connection_kind="nearest_neighbor",
    )
).with_shots(32)
```

The declaration and call stay constant as chip size or numbering changes.
Configuration binding resolves this intent deterministically against the
accepted topology and retains both the intent and selected entity table in the
bound plan. Explicit qubit sequences remain available when identity is itself
part of the experiment. The named `iq_shots` product natively owns
`(entity, shot)` axes, and target result mapping assembles the per-qubit
acquisition addresses into that one logical value. `call.entity_results()`
remains useful for fixed-arity programs that deliberately expose one named
product per concrete qubit.

Compiler-owned defaults can use the pure row maps in
`scopecat_quantum.pulse_recipes`. The complete supported example is the
[DRAG-beta workflow](../../examples/reference_lab/README.md), including parameter-axis
overlays, analysis, candidate acceptance, target lowering, and production use.

## Scaling model

Qubits, configured topology, parameter bindings, shots, and result shape
contribute to the physical workload without changing the authored meaning of a
program call. A domain compiler declares its point capacity and receives
bounded `compile_batch` requests. The target runtime may further group qubits
and chunk shots or binary results inside its own contract.

Bound programs and pulse lowering plans retain the `parallel_each`
entity-set boundary and finite repeat nodes. Recipe matching streams concrete
logical leaves without building an expanded circuit; concrete pulse branches
and scheduled events are created only when a target entry is prepared.
Inspection reports both structural and expanded operation counts, the selected
entity count, and maximum parallel width, so a GUI can show the compact intent
before drilling into its concrete realization.

Physical batch size, shot partitioning, and target placement do not enter
logical point, program, product, or measurement-record identity. This lets an
integration tune compilation, upload, and acquisition capacity while retaining
the same measurement schema and durable lineage. Point-level aggregates belong
in the canonical measurement stream; large shot-level or trace payloads cross
the data boundary as typed binary partitions rather than control-plane records.

Large programs follow three deliberately separate shapes:

1. The authored and bound-logical IR retains `parallel_each` and `repeat` as
   parameterized nodes. One template is stored regardless of entity-set size.
2. Target lowering instantiates stable entity-qualified operations only where a
   concrete schedule or placement requires them. Reordering the selected
   entities therefore does not change an entity's operation or acquisition
   identity.
3. The target artifact owns physical batching, event/acquisition limits,
   waveform memory, result volume, and result-chunk budgets. Those capacities
   may change without changing the program or result schema.

Program inspection uses the same separation. A default preview returns bounded
pages for authored, logical, scheduled, and physical layers. Subsequent queries
return just one layer page and may filter by node kind, entity, resource, parent,
or text:

```python
from scopecat.inspection import CompiledProgramInspectionQuery

preview = lab.prepare(experiment).preview(
    point="last",
    inspection_query=CompiledProgramInspectionQuery(
        layer_id="scheduled",
        entity_id="q17",
        kind="play",
        limit=128,
    ),
)
```

Each layer reports its full structural node count, matching count, returned
count, and next offset. Node entity/resource/result references are separately
bounded while retaining their full counts. This lets a GUI present an overview,
drill into a Map or Repeat aggregate, filter a concrete schedule, and inspect
physical placement constraints without receiving the complete expanded tree.

The [scalability benchmarks](../../docs/development/scalability.md) cover
multi-run calibration, shot-heavy acquisition, structured traces, and dense
spectroscopy.
