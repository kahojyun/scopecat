"""Function-authored 2-D DRAG-beta calibration experiment."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_postprocessor,
)

from quantum_lab_demo.virtual_lab.parameters import (
    q0_drag_beta_lookup,
    qubit_parameters,
)
from quantum_lab_demo.workflows.drag_beta_calibration import (
    drag_beta_program,
)

DRAG_BETA_TEMPLATE_ID = "quantum_lab_demo.workflows.drag_beta"
DRAG_BETA_EXPERIMENT_ID = "drag-beta-calibration"
DRAG_BETA_SHOTS = 64
DRAG_BETA_SPAN = Quantity(1.0, "ns")
DRAG_BETA_POINTS = 5
DEFAULT_BETAS = tuple(Quantity(value, "ns") for value in (0.0, 0.25, 0.5, 0.75, 1.0))
DEFAULT_AMPLIFICATIONS = (1, 2, 3)


_BETA_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
BETA = sc.coordinate("beta", _BETA_VALUE_TYPE)
AMPLIFICATION = sc.coordinate(
    "amplification",
    sc.ScalarType(sc.IntType(minimum=1)),
)

_DRAG_BETA_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@sc.module(id="quantum_lab_demo.workflows.drag_beta.capture")
def drag_beta_capture(
    amplification: Annotated[sc.Input[int], sc.IntType(minimum=1)],
    beta: Annotated[
        sc.Input[Quantity],
        sc.ScalarType(sc.QuantityType(unit="ns")),
    ],
):
    """Capture and discriminate one DRAG-beta program call."""

    call = (
        drag_beta_program(
            qubit="q0",
            amplification=amplification,
            beta=beta,
        )
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(DRAG_BETA_SHOTS)
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
        discriminator=_DRAG_BETA_DISCRIMINATOR,
    )
    return body.measurement_postprocessors(postprocessor)


def _drag_beta_experiment_body(scan: sc.Scan) -> sc.ExperimentBody:
    capture = drag_beta_capture(
        amplification=AMPLIFICATION,
        beta=q0_drag_beta_lookup(),
    )
    return (
        sc.experiment(capture)
        .scan(scan)
        .record_product(
            capture.products.probability_0,
            capture.products.probability_1,
        )
    )


@sc.template(
    id=DRAG_BETA_TEMPLATE_ID,
    kind=DRAG_BETA_EXPERIMENT_ID,
)
def drag_beta_template() -> sc.ExperimentBody:
    """Scan pulse DRAG beta against gate amplification in one program."""

    return _drag_beta_experiment_body(
        sc.cartesian(
            sc.param_axis(
                BETA,
                q0_drag_beta_lookup(),
                span=DRAG_BETA_SPAN,
                points=DRAG_BETA_POINTS,
            ),
            sc.axis(AMPLIFICATION, DEFAULT_AMPLIFICATIONS),
        )
    )


@sc.scratch(
    id="quantum_lab_demo.workflows.drag_beta.scratch",
    kind=DRAG_BETA_EXPERIMENT_ID,
)
def drag_beta_scratch_experiment(
    *,
    betas: Sequence[Quantity] = DEFAULT_BETAS,
    amplifications: Sequence[int] = DEFAULT_AMPLIFICATIONS,
) -> sc.ExperimentBody:
    """Build the same 2-D semantics without a reusable template."""

    return _drag_beta_experiment_body(
        sc.cartesian(
            sc.param_axis(
                BETA,
                q0_drag_beta_lookup(),
                tuple(betas),
            ),
            sc.axis(AMPLIFICATION, tuple(amplifications)),
        )
    )


__all__ = [
    "AMPLIFICATION",
    "BETA",
    "DEFAULT_AMPLIFICATIONS",
    "DEFAULT_BETAS",
    "DRAG_BETA_EXPERIMENT_ID",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SHOTS",
    "DRAG_BETA_SPAN",
    "DRAG_BETA_TEMPLATE_ID",
    "drag_beta_capture",
    "drag_beta_program",
    "drag_beta_scratch_experiment",
    "drag_beta_template",
]
