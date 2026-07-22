"""readout modules."""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_multiplexed_readout_program,
    build_readout_program,
)
from quantum_lab_demo.experiments.ids import (
    MULTIPLEXED_READOUT_TEMPLATE_ID,
    READOUT_TEMPLATE_ID,
)
from quantum_lab_demo.experiments.parameter_refs import qubit_param
from quantum_lab_demo.experiments.points import READOUT_FREQUENCY

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_QUBIT_SERIES = sc.SeriesType(_QUBIT)
_QUANTITY = sc.ScalarType(sc.QuantityType())


@sc.module(id="quantum_lab_demo.experiments.readout.capture")
def READOUT_CAPTURE_MODULE():
    return (
        sc.module_body()
        .resource(
            "readout",
            requires=("acquire_iq",),
        )
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=sc.parameter("repetitions", _QUANTITY),
        )
        .product("raw_iq", unit="ratio", dtype="complex128")
        .product("probability_0", "probability_1", unit=None)
        .product("state0_iq", unit="ratio", dtype="complex128")
        .product("state1_iq", unit="ratio", dtype="complex128")
        .product("state0_iq_stdev", unit=None)
        .product("state1_iq_stdev", unit=None)
        .acquire(
            "read-capture",
            "raw_iq",
            "probability_0",
            "probability_1",
            "state0_iq",
            "state1_iq",
            "state0_iq_stdev",
            "state1_iq_stdev",
            resource="readout",
            capability="acquire_iq",
        )
    )


@sc.module(id=READOUT_TEMPLATE_ID)
def READOUT_MODULE(
    qubit: Annotated[sc.Input[str], _QUBIT],
):
    qubit_ref = cast("sc.ValueRef", qubit)
    build_program = sc.compute(
        "build-readout-frequency-program",
        fn=build_readout_program,
        output_type=sc.ScalarType(sc.PayloadType("readout_program")),
        inputs={
            "qubit": qubit_ref,
            "frequency": READOUT_FREQUENCY,
            "power": qubit_param("readout_power", qubit_ref),
        },
    )
    return (
        sc.module_body()
        .resource(
            "readout",
            requires=("readout_pulse", "acquire_iq"),
            for_entities=(qubit_ref,),
        )
        .computes(build_program)
        .bind_field(
            "readout",
            capability="readout_pulse",
            field="program",
            value=build_program.output,
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
            value=qubit_param("readout_power", qubit_ref),
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


@sc.module(id="quantum_lab_demo.experiments.readout.multiplexed_pulse")
def MULTIPLEXED_READOUT_PULSE_MODULE(
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    readout_power: Annotated[sc.Input[sc.Quantity], _QUANTITY],
):
    qubits_ref = cast("sc.ValueRef", qubits)
    readout_power_ref = cast("sc.ValueRef", readout_power)
    build_program = sc.compute(
        "build-multiplexed-readout-program",
        fn=build_multiplexed_readout_program,
        output_type=sc.ScalarType(sc.PayloadType("readout_program")),
        inputs={
            "qubits": qubits_ref,
            "frequency": READOUT_FREQUENCY,
            "power": readout_power_ref,
        },
    )
    return (
        sc.module_body()
        .resource(
            "readout",
            requires=("readout_pulse", "acquire_iq"),
            for_entities=(qubits_ref,),
        )
        .computes(build_program)
        .bind_field(
            "readout",
            capability="readout_pulse",
            field="program",
            value=build_program.output,
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
            value=readout_power_ref,
        )
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=sc.parameter("repetitions", _QUANTITY),
        )
        .product(
            "multiplexed_iq",
            unit="ratio",
            dtype="complex128",
            axes=(sc.entity_axis("qubit", qubits_ref),),
        )
        .acquire(
            "read-multiplexed-iq",
            "multiplexed_iq",
            resource="readout",
            capability="acquire_iq",
        )
    )


@sc.module(id=MULTIPLEXED_READOUT_TEMPLATE_ID)
def MULTIPLEXED_READOUT_MODULE(
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
):
    qubits_ref = cast("sc.ValueRef", qubits)
    return (
        sc.module_body()
        .resource(
            "readout",
            requires=("acquire_iq",),
            for_entities=(qubits_ref,),
        )
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=sc.parameter("repetitions", _QUANTITY),
        )
        .product(
            "multiplexed_iq",
            unit="ratio",
            dtype="complex128",
            axes=(sc.entity_axis("qubit", qubits_ref),),
        )
        .acquire(
            "read-multiplexed-iq",
            "multiplexed_iq",
            resource="readout",
            capability="acquire_iq",
        )
    )


__all__ = [
    "MULTIPLEXED_READOUT_MODULE",
    "MULTIPLEXED_READOUT_PULSE_MODULE",
    "READOUT_CAPTURE_MODULE",
    "READOUT_MODULE",
]
