"""Function-authored 2-D DRAG-beta calibration experiment."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_postprocessor,
)

from quantum_lab_demo.virtual_lab.parameters import (
    QUBIT_PARAMETER_TABLE_TYPE,
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
DEFAULT_AMPLIFICATIONS = (1, 2, 3)
PROBABILITY_0_RECORD_ID = "capture/probability_0"
PROBABILITY_1_RECORD_ID = "capture/probability_1"


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
    module: sc.ModuleContext,
    amplification: Annotated[sc.Input[int], sc.IntType(minimum=1)],
    beta: Annotated[
        sc.Input[Quantity],
        sc.ScalarType(sc.QuantityType(unit="ns")),
    ],
    qubits: Annotated[
        sc.Input[list[dict[str, object]]],
        QUBIT_PARAMETER_TABLE_TYPE,
    ],
) -> None:
    """Capture and discriminate one DRAG-beta program call."""

    call = (
        drag_beta_program(
            qubit="q0",
            amplification=amplification,
            beta=beta,
        )
        .with_compiler_inputs(qubits=sc.input_ref(qubits))
        .with_shots(DRAG_BETA_SHOTS)
    )
    module.call(call)
    probability_0 = module.product("probability_0", unit="ratio")
    probability_1 = module.product("probability_1", unit="ratio")
    postprocessor = binary_iq_probability_postprocessor(
        "binary-iq-probability",
        iq_shots=call.results.iq_shots,
        probability_0=probability_0,
        probability_1=probability_1,
        discriminator=_DRAG_BETA_DISCRIMINATOR,
    )
    module.measurement_postprocessor(postprocessor)


def _drag_beta_experiment_body(
    experiment: sc.ExperimentContext,
    *scans: sc.Scan,
) -> None:
    capture = experiment.run(
        drag_beta_capture(
            amplification=AMPLIFICATION,
            beta=q0_drag_beta_lookup(),
            qubits=qubit_parameters(),
        )
    )
    experiment.scan(*scans)
    experiment.record(
        capture.products.probability_0,
        capture.products.probability_1,
    )


@sc.template(
    id=DRAG_BETA_TEMPLATE_ID,
    kind=DRAG_BETA_EXPERIMENT_ID,
)
def drag_beta_template(experiment: sc.ExperimentContext) -> None:
    """Scan pulse DRAG beta against gate amplification in one program."""

    _drag_beta_experiment_body(
        experiment,
        sc.param_axis(
            BETA,
            q0_drag_beta_lookup(),
            span=DRAG_BETA_SPAN,
            points=DRAG_BETA_POINTS,
        ),
        sc.axis(AMPLIFICATION, DEFAULT_AMPLIFICATIONS),
    )


__all__ = [
    "AMPLIFICATION",
    "BETA",
    "DEFAULT_AMPLIFICATIONS",
    "DRAG_BETA_EXPERIMENT_ID",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SHOTS",
    "DRAG_BETA_SPAN",
    "DRAG_BETA_TEMPLATE_ID",
    "PROBABILITY_0_RECORD_ID",
    "PROBABILITY_1_RECORD_ID",
    "drag_beta_capture",
    "drag_beta_program",
    "drag_beta_template",
]
