"""Recommended scalar readout-frequency workflow."""

from __future__ import annotations

import scopecat as sc
from scopecat_quantum import authoring as q

from quantum_lab_demo.virtual_lab.parameters import QUBIT_PARAMETER_TABLE

READOUT_TEMPLATE_ID = "quantum_lab_demo.workflows.readout_frequency"
_QUANTITY = sc.ScalarType(sc.QuantityType())
READOUT_FREQUENCY = sc.coordinate("readout_frequency", _QUANTITY)


def _qubit_parameter(column: str, qubit: sc.Input[str]) -> sc.ValueRef:
    return sc.parameter_lookup(
        QUBIT_PARAMETER_TABLE,
        key={"qubit": qubit},
        column=column,
        value_type=_QUANTITY,
    )


@sc.module(id=READOUT_TEMPLATE_ID)
def readout_module(
    qubit: q.QubitInput,
):
    """Configure a scalar readout fixture; quantum programs use ``@q.program``."""

    qubit_ref = sc.input_ref(qubit)
    return (
        sc.module_body()
        .resource(
            "readout",
            requires=("readout_pulse", "acquire_iq"),
            for_entities=(qubit_ref,),
        )
        .bind_field(
            "readout",
            capability="readout_pulse",
            field="frequency",
            value=READOUT_FREQUENCY,
        )
        .bind_field(
            "readout",
            capability="readout_pulse",
            field="power",
            value=_qubit_parameter("readout_power", qubit_ref),
        )
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=sc.parameter("repetitions", _QUANTITY),
        )
        .product("raw_iq", unit="ratio", dtype="complex128")
        .product("state0_iq", unit="ratio", dtype="complex128")
        .product("state1_iq", unit="ratio", dtype="complex128")
        .product("state0_iq_stdev", unit=None)
        .product("state1_iq_stdev", unit=None)
        .acquire(
            "read-iq",
            "raw_iq",
            "state0_iq",
            "state1_iq",
            "state0_iq_stdev",
            "state1_iq_stdev",
            resource="readout",
            capability="acquire_iq",
        )
    )


@sc.template(
    id=READOUT_TEMPLATE_ID,
    kind="readout_frequency",
    label="readout frequency",
)
def readout_frequency_template(
    qubit: q.QubitInput,
) -> sc.ExperimentBody:
    """Teach the core workflow with scalar instrument state and response data."""

    readout = readout_module(qubit=qubit)
    return (
        sc.experiment(readout)
        .scan(
            READOUT_FREQUENCY,
            center=_qubit_parameter("readout_frequency", qubit),
            span=sc.Quantity(value=100.0, unit="MHz"),
            points=5,
        )
        .record_product(
            readout.products.raw_iq,
            readout.products.state0_iq,
            readout.products.state1_iq,
            readout.products.state0_iq_stdev,
            readout.products.state1_iq_stdev,
        )
    )


__all__ = [
    "READOUT_FREQUENCY",
    "READOUT_TEMPLATE_ID",
    "readout_frequency_template",
    "readout_module",
]
