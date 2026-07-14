# Scopecat Quantum

Hardware-independent quantum building blocks for Scopecat.

This package owns logical gates, circuits, pulses, calibration selection, and
the checked boundary to a target compiler. It does not own experiment
templates, laboratory calibration values, physical wiring, concrete hardware
artifacts, device runtimes, or response models; those belong to the laboratory
package that consumes it.

The `scopecat_quantum.authoring` facade creates opaque circuit handles and
binds symbolic inputs into verified circuit IR:

```python
from scopecat_quantum import GateParameterKind, authoring

q0 = authoring.qubit("q0")
x_count = authoring.scalar_input("x_count", GateParameterKind.INTEGER)
x = authoring.single_qubit_gate("x")
readout = authoring.measure(q0, result="raw_iq")
circuit = authoring.circuit(
    "x-count",
    authoring.sequence(authoring.repeat(x(q0), x_count), readout),
)
bound = authoring.bind_circuit(circuit, {"x_count": 3})
```

Laboratory adapters connect circuits to Scopecat through
`circuit_domain_program` and `circuit_domain_call`, then implement the public
`scopecat.sdk.domain` contracts. The exact invariants of each lowering stage are
documented in the corresponding module docstrings.
