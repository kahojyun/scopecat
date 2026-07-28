"""Quantum-lab interface identities shared by routing and virtual devices."""

from __future__ import annotations

from scopecat.kernel.value_types import Payload, Scalar
from scopecat.sdk.instruments import (
    InterfaceRef,
    InterfaceSpec,
    OperationArgumentRef,
    OperationRef,
    interface,
    operation,
    operation_argument,
)

PLAY_PULSE_PROGRAM: InterfaceRef = InterfaceRef("quantum_lab.play_pulse_program/v1")
PLAY_PULSE_PROGRAM_PLAY: OperationRef = PLAY_PULSE_PROGRAM.operation("play")
PLAY_PULSE_PROGRAM_PROGRAM: OperationArgumentRef = PLAY_PULSE_PROGRAM_PLAY.argument(
    "program"
)
READOUT_PULSE: InterfaceRef = InterfaceRef("quantum_lab.readout_pulse/v1")
ACQUIRE_IQ: InterfaceRef = InterfaceRef("quantum_lab.acquire_iq/v1")


def play_pulse_program_interface() -> InterfaceSpec:
    return interface(
        PLAY_PULSE_PROGRAM.interface_id,
        label="Play pulse program",
        operations=[
            operation(
                PLAY_PULSE_PROGRAM_PLAY.operation_id,
                label="Play pulse program",
                arguments=[
                    operation_argument(
                        PLAY_PULSE_PROGRAM_PROGRAM.argument_id,
                        value_type=Scalar(Payload("pulse_program")),
                        label="Pulse program",
                    )
                ],
            )
        ],
    )


def readout_pulse_interface() -> InterfaceSpec:
    return interface(READOUT_PULSE.interface_id, label="Readout pulse")


def acquire_iq_interface() -> InterfaceSpec:
    return interface(ACQUIRE_IQ.interface_id, label="Acquire IQ")


__all__ = [
    "ACQUIRE_IQ",
    "PLAY_PULSE_PROGRAM",
    "PLAY_PULSE_PROGRAM_PLAY",
    "PLAY_PULSE_PROGRAM_PROGRAM",
    "READOUT_PULSE",
    "acquire_iq_interface",
    "play_pulse_program_interface",
    "readout_pulse_interface",
]
