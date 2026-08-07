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
injects compiler inputs, measurement postprocessing, recording policy, and
independent auxiliary-device work; the program call remains one domain effect
rather than becoming the whole experiment. The
[reference lab runner](../../examples/reference_lab/README.md) shows that path.

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

Physical batch size and target placement do not enter logical point, program,
or product identity. This lets an integration tune compilation, upload, and
acquisition capacity while retaining the same measurement schema and durable
lineage. Point-level aggregates belong in the canonical measurement stream;
large shot-level or trace payloads should cross the data boundary as typed
binary content rather than control-plane records.

The [scalability benchmarks](../../docs/scalability-benchmarks.md) cover
multi-run calibration, shot-heavy acquisition, structured traces, and dense
spectroscopy.
