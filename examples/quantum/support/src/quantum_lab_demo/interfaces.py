"""Quantum-lab interface identities shared by routing and virtual devices."""

from __future__ import annotations

from scopecat.sdk.instruments import InterfaceSpec, interface, payload_property

PLAY_PULSE_PROGRAM = "quantum_lab.play_pulse_program/v1"
READOUT_PULSE = "quantum_lab.readout_pulse/v1"
ACQUIRE_IQ = "quantum_lab.acquire_iq/v1"


def play_pulse_program_interface() -> InterfaceSpec:
    return interface(
        PLAY_PULSE_PROGRAM,
        label="Play pulse program",
        properties=[
            payload_property(
                "program",
                schema_id="pulse_program",
                label="Pulse program",
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
