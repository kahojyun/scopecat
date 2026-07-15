# Scopecat Quantum

Hardware-independent quantum building blocks for Scopecat.

This package owns logical gates, circuits, pulses, calibration selection, and
the checked boundary to a target compiler. It does not own experiment
templates, laboratory calibration values, physical wiring, concrete hardware
artifacts, device runtimes, or response models; those belong to the laboratory
package that consumes it.

The `scopecat_quantum.authoring` facade creates opaque handles for one unified
gate-and-pulse DSL. `sequence`, `parallel`, and `repeat` accept both logical
gate calls and physical pulse statements. Logical-only and mixed work both use
the same `Program` declaration and binding path:

```python
from scopecat_quantum import GateParameterKind, authoring

q0 = authoring.qubit("q0")
x_count = authoring.scalar_input("x_count", GateParameterKind.INTEGER)
x = authoring.single_qubit_gate("x")
readout = authoring.measure(q0, result="raw_iq")
declaration = authoring.program(
    "x-count",
    authoring.sequence(authoring.repeat(x(q0), x_count), readout),
)
bound = authoring.bind(declaration, {"x_count": 3})
```

An explicit implementation keeps the logical gate identity while substituting
a local pulse implementation. Giving it a `candidate` ID records calibration
lifecycle identity; omitting that ID represents a selected production
implementation. Only unresolved logical gates are selected from the
calibration catalog:

```python
import scopecat as sc
from scopecat import Quantity
from scopecat_quantum import authoring

q0 = authoring.qubit("q0")
beta = authoring.input(
    "beta",
    sc.ScalarType(sc.QuantityType(unit="ns")),
)
x90 = authoring.single_qubit_gate("x90")
candidate = authoring.implements(
    x90(q0),
    authoring.play(
        authoring.drive(q0),
        authoring.drag(
            duration=Quantity(16, "ns"),
            amplitude=Quantity(0.2, "arb"),
            sigma=Quantity(4, "ns"),
            beta=beta,
        ),
    ),
    candidate="x90.drag",
)
declaration = authoring.program(
    "x90-drag-point",
    authoring.sequence(x90(q0), authoring.repeat(candidate, 3)),
)
bound = authoring.bind(declaration, {"beta": Quantity(0.75, "ns")})
```

Two-qubit gates use the same surface. Couplers are opaque physical resources,
not extra gate operands: declare them separately and explicitly authorize only
the couplers that an implementation may drive. Pulse templates bind qubits and
couplers through one ordered `elements` interface while preserving their
distinct types:

```python
from scopecat import Quantity
from scopecat_quantum import authoring

q0 = authoring.qubit("q0")
q1 = authoring.qubit("q1")
c01 = authoring.coupler("coupler-q0-q1")
cz = authoring.two_qubit_gate("cz")

formal_coupler = authoring.coupler("coupler")
cz_flux = authoring.pulse_template(
    "cz.flux",
    authoring.play(
        authoring.flux(formal_coupler),
        authoring.constant(
            duration=Quantity(32, "ns"),
            amplitude=Quantity(0.24, "arb"),
        ),
    ),
    elements=(formal_coupler,),
)
candidate = authoring.implements(
    cz(q0, q1),
    cz_flux(c01),
    resources=(c01,),
    candidate="cz.conditional-phase",
)
declaration = authoring.program("cz-point", candidate)
```

The same `PulseTemplate` can therefore back both a scanned candidate and an
accepted production gate. A laboratory module can bind its `ProgramInput`
directly from `scopecat.parameter_lookup(...)` in `domain_call`, so the
active configuration remains an explicit typed DSL dependency rather than
hidden adapter state.

Mixed verification projects the source twice: a complete logical circuit for
semantic checks and an unresolved circuit for exact calibration selection.
Lowering then converges calibrated gates, explicit implementations, and inline
pulses into the existing `PulseProgram`. Target compilers still receive only a
validated `ScheduledPulseProgram`; mixed authoring does not widen the hardware
boundary.

Laboratory adapters connect every authored declaration to Scopecat through
`domain_program` / `domain_call`, then implement the public
`scopecat.sdk.domain` contracts. Pure logical programs still project to the
internal verified Circuit IR for calibration selection; that distinction no
longer creates another user-facing entry point.
