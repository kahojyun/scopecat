"""Function-based authoring for the fake X-count workflow."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

import scopecat as sc
from scopecat_quantum import authoring as quantum
from scopecat_quantum.gates import GateParameterKind
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_postprocessor,
)
from scopecat_quantum.standard_gates import X

from quantum_lab_demo.virtual_lab.parameters import qubit_parameters

FAKE_X_COUNT_TEMPLATE_ID = "quantum_lab_demo.workflows.fake_x_count"
FAKE_X_COUNT_EXPERIMENT_ID = "fake-x-count"
FAKE_X_COUNT_SHOTS = 32
DEFAULT_X_COUNTS = (0, 1, 2, 4)

X_COUNT = sc.coordinate(
    "x_count",
    sc.ScalarType(sc.IntType(minimum=0)),
)

_X_COUNT_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@quantum.program(id="fake-x-count")
def x_count_program(
    qubit: quantum.Qubit,
    x_count: Annotated[int, GateParameterKind.INTEGER],
) -> quantum.QuantumFragment:
    """Repeat X on one logical qubit, then acquire integrated IQ shots."""

    return quantum.sequence(
        quantum.repeat(X(qubit), x_count),
        quantum.measure(qubit, result="iq_shots"),
    )


@sc.module(id="quantum_lab_demo.workflows.fake_x_count.capture")
def fake_x_count_capture(
    x_count: Annotated[sc.Input[int], sc.IntType(minimum=0)],
):
    """Capture and discriminate one fake X-count program call."""

    call = (
        x_count_program(
            qubit="q0",
            x_count=x_count,
        )
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(FAKE_X_COUNT_SHOTS)
    )
    body = (
        sc.module_body()
        .use(call)
        .product("probability_0", "probability_1", unit="ratio")
    )
    postprocessor = binary_iq_probability_postprocessor(
        "binary-iq-probability",
        iq_shots=call.results.iq_shots,
        probability_0=body.products.probability_0,
        probability_1=body.products.probability_1,
        discriminator=_X_COUNT_DISCRIMINATOR,
    )
    return body.measurement_postprocessors(postprocessor)


def _fake_x_count_body(x_counts: Sequence[int]) -> sc.ExperimentBody:
    capture = fake_x_count_capture(x_count=X_COUNT)
    return (
        sc.experiment(capture)
        .scan(X_COUNT, tuple(x_counts))
        .record_product(
            capture.products.probability_0,
            capture.products.probability_1,
        )
    )


@sc.template(
    id=FAKE_X_COUNT_TEMPLATE_ID,
    kind=FAKE_X_COUNT_EXPERIMENT_ID,
)
def fake_x_count_template() -> sc.ExperimentBody:
    """Compile q0 X repetitions and discriminate the digitizer IQ."""

    return _fake_x_count_body(DEFAULT_X_COUNTS)


@sc.scratch(
    id="quantum_lab_demo.workflows.fake_x_count.scratch",
    kind=FAKE_X_COUNT_EXPERIMENT_ID,
)
def fake_x_count_scratch(
    *,
    x_counts: Sequence[int] = DEFAULT_X_COUNTS,
) -> sc.ExperimentBody:
    """Build the same workflow semantics with caller-selected X counts."""

    return _fake_x_count_body(x_counts)


__all__ = [
    "DEFAULT_X_COUNTS",
    "FAKE_X_COUNT_EXPERIMENT_ID",
    "FAKE_X_COUNT_SHOTS",
    "FAKE_X_COUNT_TEMPLATE_ID",
    "X_COUNT",
    "fake_x_count_capture",
    "fake_x_count_scratch",
    "fake_x_count_template",
    "x_count_program",
]
