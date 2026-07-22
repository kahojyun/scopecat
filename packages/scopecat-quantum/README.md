# Scopecat Quantum

Hardware-independent quantum building blocks for Scopecat.

This package provides logical gates, circuits, pulses, calibration selection,
and the checked boundary to a target compiler. Laboratory-specific templates,
calibration values, wiring, hardware artifacts, runtimes, and response models
stay in the package that integrates Scopecat with the laboratory.

The `scopecat_quantum.authoring` facade creates opaque handles for one unified
gate-and-pulse DSL. `sequence`, `parallel`, and `repeat` accept both logical
gate calls and physical pulse statements. Logical-only and mixed work both use
the same `Program` declaration and binding path:

```python
from typing import Annotated

from scopecat_quantum import GateParameterKind, authoring

x = authoring.single_qubit_gate("x")


@authoring.program(id="x-count")
def x_count_program(
    qubit: authoring.Qubit,
    x_count: Annotated[int, GateParameterKind.INTEGER],
) -> authoring.QuantumFragment:
    return authoring.sequence(
        authoring.repeat(x(qubit), x_count),
        authoring.measure(qubit, result="raw_iq"),
    )


call = x_count_program(qubit="q0", x_count=3).with_shots(32)

print(x_count_program.describe())
print(x_count_program.draw())
```

The program call accepts exactly the ports in the Python definition.
`with_shots(...)` separately selects acquisition count without adding a hidden
parameter to that signature.

An explicit implementation keeps the logical gate identity while substituting
a local pulse implementation. Giving it a `candidate` ID records calibration
lifecycle identity; omitting that ID represents a selected production
implementation. Only unresolved logical gates are selected from the
calibration catalog:

```python
from typing import Annotated

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum import authoring

x90 = authoring.single_qubit_gate("x90")
beta_type = sc.ScalarType(sc.QuantityType(unit="ns"))


@authoring.implementation(of=x90, candidate="x90.drag")
def x90_drag_candidate(
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


@authoring.program(id="x90-drag-point")
def x90_drag_point(
    qubit: authoring.Qubit,
    beta: Annotated[Quantity, beta_type],
) -> authoring.QuantumFragment:
    candidate = x90_drag_candidate(qubit, beta=beta)
    return authoring.sequence(x90(qubit), authoring.repeat(candidate, 3))


call = x90_drag_point(qubit="q0", beta=Quantity(0.75, "ns"))
```

Two-qubit gates use the same surface. Couplers are typed implementation
resources, not extra gate operands. The implementation call carries the two
logical operands and its physical coupler together:

```python
from scopecat import Quantity
from scopecat_quantum import authoring

cz = authoring.two_qubit_gate("cz")


@authoring.implementation(of=cz, candidate="cz.conditional-phase")
def cz_flux(
    control: authoring.Qubit,
    target: authoring.Qubit,
    coupler: authoring.Coupler,
) -> authoring.QuantumFragment:
    return authoring.play(
        authoring.flux(coupler),
        authoring.constant(
            duration=Quantity(32, "ns"),
            amplitude=Quantity(0.24, "arb"),
        ),
    )


@authoring.program(id="cz-point")
def cz_point(
    control: authoring.Qubit,
    target: authoring.Qubit,
    coupler: authoring.Coupler,
) -> authoring.QuantumFragment:
    return cz_flux(control, target, coupler)


call = cz_point(
    control="q0",
    target="q1",
    coupler="coupler-q0-q1",
)
```

The same `@pulse_template` function can be composed inside scanned and
production `@implementation` functions. Program inputs may bind directly to Scopecat values such as
`scopecat.parameter_lookup(...)`, keeping active configuration visible in the
authored experiment instead of hidden mutable state.

For calibration scans, `scopecat.param_axis(...)` overlays one referenced
parameter cell per point, so every `parameter_lookup(...)` observes the same
scanned value for that cell. The fitted result can use Scopecat's normal
proposal, review, and activation lifecycle.

Calling a `Program` returns a `QuantumProgramCall` that owns its domain effect,
execution options, and named result products. Compose it directly with
`sc.module_body().use(call)` when host-side transforms are needed, or with
`sc.experiment(call)` when the program already expresses the complete run.
The `ExperimentSystem` compiler keeps target-specific lowering behind that
boundary.
