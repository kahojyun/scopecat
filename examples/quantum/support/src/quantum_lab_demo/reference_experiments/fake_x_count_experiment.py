"""Public authoring for the fake X-count Workspace reference."""

from __future__ import annotations

from collections.abc import Sequence

import scopecat as sc
from scopecat_quantum import (
    BinaryIqDiscriminator,
    GateParameterKind,
    IqCentroid,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as quantum

FAKE_X_COUNT_TEMPLATE_ID = "quantum_lab_demo.reference.fake_x_count"
FAKE_X_COUNT_EXPERIMENT_ID = "fake-x-count"
FAKE_X_COUNT_SHOTS = 32
DEFAULT_X_COUNTS = (0, 1, 2, 4)


X_COUNT = sc.point(
    "x_count",
    sc.ScalarType(sc.IntType(minimum=0)),
)

_Q0 = quantum.qubit("q0")
_X_COUNT_INPUT = quantum.scalar_input("x_count", GateParameterKind.INTEGER)
_X_GATE = quantum.single_qubit_gate("x")
_READOUT = quantum.measure(_Q0, result="iq_shots")
X_COUNT_PROGRAM = quantum.program(
    "fake-x-count",
    quantum.sequence(
        quantum.repeat(_X_GATE(_Q0), _X_COUNT_INPUT),
        _READOUT,
    ),
)
_X_COUNT_DOMAIN_PROGRAM = quantum.domain_program(X_COUNT_PROGRAM)
_X_COUNT_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_X_COUNT_TRANSFORM = binary_iq_probability_transform(
    "binary-iq-probability",
    iq_shots="integrated_iq_shots",
    probability_0="probability_0",
    probability_1="probability_1",
    discriminator=_X_COUNT_DISCRIMINATOR,
)

FAKE_X_COUNT_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.reference.fake_x_count.capture")
    .product(
        "integrated_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(FAKE_X_COUNT_SHOTS),),
    )
    .product("probability_0", "probability_1", unit="ratio")
    .measurement_transforms(_X_COUNT_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = FAKE_X_COUNT_CAPTURE_MODULE.instantiate("capture")


def fake_x_count_domain_execution(
    iq_shots: sc.ProductRef,
    *,
    x_count: sc.ValueRef = X_COUNT,
    id: str | None = None,  # noqa: A002
) -> sc.DomainExecution:
    """Bind the reference quantum program to one composed capture product."""

    return quantum.domain_execution(
        _X_COUNT_DOMAIN_PROGRAM,
        id=id,
        inputs={_X_COUNT_INPUT: x_count},
        results={_READOUT.result: iq_shots},
    )


_X_COUNT_EXECUTION = fake_x_count_domain_execution(
    _TEMPLATE_CAPTURE.products.integrated_iq_shots
)
FAKE_X_COUNT_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.fake_x_count.root")
    .use(_TEMPLATE_CAPTURE)
    .domain(_X_COUNT_EXECUTION)
    .template(
        FAKE_X_COUNT_TEMPLATE_ID,
        kind=FAKE_X_COUNT_EXPERIMENT_ID,
    )
    .experiment_id(FAKE_X_COUNT_EXPERIMENT_ID)
    .scan(X_COUNT, DEFAULT_X_COUNTS)
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_0,
        record_id="probability_0",
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_1,
        record_id="probability_1",
    )
    .label("Fake AWG X-count scan")
    .description(
        "Compile calibrated q0 X repetitions into one fake AWG list and "
        "discriminate digitizer IQ."
    )
)


def fake_x_count_scratch_experiment(
    lab: sc.Workspace,
    *,
    x_counts: Sequence[int] = DEFAULT_X_COUNTS,
) -> sc.Experiment:
    """Build the same reference semantics through the scratch Experiment UX."""

    capture = FAKE_X_COUNT_CAPTURE_MODULE.instantiate("capture")
    execution = fake_x_count_domain_execution(capture.products.integrated_iq_shots)
    return (
        lab.experiment("fake X-count scratch")
        .use(capture)
        .domain(execution)
        .scan(X_COUNT, tuple(x_counts))
        .record_product(
            capture.products.probability_0,
            record_id="probability_0",
        )
        .record_product(
            capture.products.probability_1,
            record_id="probability_1",
        )
    )


__all__ = [
    "DEFAULT_X_COUNTS",
    "FAKE_X_COUNT_CAPTURE_MODULE",
    "FAKE_X_COUNT_EXPERIMENT_ID",
    "FAKE_X_COUNT_SHOTS",
    "FAKE_X_COUNT_TEMPLATE",
    "FAKE_X_COUNT_TEMPLATE_ID",
    "X_COUNT",
    "X_COUNT_PROGRAM",
    "fake_x_count_domain_execution",
    "fake_x_count_scratch_experiment",
]
