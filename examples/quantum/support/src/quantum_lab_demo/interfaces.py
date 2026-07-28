"""Quantum-lab interface identities shared by routing and virtual devices."""

from __future__ import annotations

from scopecat.kernel.value_types import Payload, Scalar
from scopecat.sdk.instruments import (
    InterfaceSpec,
    interface,
    operation,
    operation_argument,
)

PLAY_PULSE_PROGRAM = "quantum_lab.play_pulse_program/v1"
READOUT_PULSE = "quantum_lab.readout_pulse/v1"
ACQUIRE_IQ = "quantum_lab.acquire_iq/v1"


def play_pulse_program_interface() -> InterfaceSpec:
    return interface(
        PLAY_PULSE_PROGRAM,
        label="Play pulse program",
        operations=[
            operation(
                "play",
                label="Play pulse program",
                arguments=[
                    operation_argument(
                        "program",
                        value_type=Scalar(Payload("pulse_program")),
                        label="Pulse program",
                    )
                ],
            )
        ],
    )


def readout_pulse_interface() -> InterfaceSpec:
    return interface(READOUT_PULSE, label="Readout pulse")


def acquire_iq_interface() -> InterfaceSpec:
    return interface(ACQUIRE_IQ, label="Acquire IQ")


__all__ = [
    "ACQUIRE_IQ",
    "PLAY_PULSE_PROGRAM",
    "READOUT_PULSE",
    "acquire_iq_interface",
    "play_pulse_program_interface",
    "readout_pulse_interface",
]
