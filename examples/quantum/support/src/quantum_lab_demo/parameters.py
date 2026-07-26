"""Python-owned initial parameter values for the runnable quantum lab."""

from __future__ import annotations

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.records.parameter import (
    ParameterAtomValue,
    ParameterSnapshot,
    ScalarParameterValue,
    TableParameterValue,
)


def quantum_lab_parameter_snapshot() -> ParameterSnapshot:
    """Build the initial scalar and calibration tables reviewed in source."""

    return ParameterSnapshot(
        id="templates-parameter-snapshot",
        values=(
            ScalarParameterValue(
                id="repetitions",
                value=_quantity(128.0, "count"),
            ),
            TableParameterValue(
                id="qubits",
                rows=(
                    _qubit_row(
                        "q0",
                        rabi_length_ns=50.0,
                        rabi_amplitude=0.35,
                        drag_beta_ns=0.5,
                        drive_ghz=5.0,
                        readout_ghz=6.5,
                        readout_dbm=-20.0,
                    ),
                    _qubit_row(
                        "q1",
                        rabi_length_ns=48.0,
                        rabi_amplitude=0.32,
                        drag_beta_ns=0.45,
                        drive_ghz=5.2,
                        readout_ghz=6.7,
                        readout_dbm=-21.0,
                    ),
                    _qubit_row(
                        "q2",
                        rabi_length_ns=52.0,
                        rabi_amplitude=0.3,
                        drag_beta_ns=0.55,
                        drive_ghz=5.35,
                        readout_ghz=6.85,
                        readout_dbm=-22.0,
                    ),
                    _qubit_row(
                        "q3",
                        rabi_length_ns=46.0,
                        rabi_amplitude=0.31,
                        drag_beta_ns=0.6,
                        drive_ghz=5.48,
                        readout_ghz=6.95,
                        readout_dbm=-22.5,
                    ),
                ),
            ),
            TableParameterValue(
                id="two_qubit_gates",
                rows=(
                    _two_qubit_gate_row(
                        "q0",
                        "q1",
                        control_echo=0.12,
                        partner_echo=0.1,
                        parking_flux=0.03,
                        coupler_amplitude=0.2,
                    ),
                    _two_qubit_gate_row(
                        "q2",
                        "q3",
                        control_echo=0.11,
                        partner_echo=0.105,
                        parking_flux=0.028,
                        coupler_amplitude=0.19,
                    ),
                ),
            ),
        ),
    )


def _qubit_row(
    qubit_id: str,
    *,
    rabi_length_ns: float,
    rabi_amplitude: float,
    drag_beta_ns: float,
    drive_ghz: float,
    readout_ghz: float,
    readout_dbm: float,
) -> dict[str, ParameterAtomValue]:
    return {
        "qubit": EntityRef(id=qubit_id, kind="logical_qubit"),
        "rabi_pulse_length": _quantity(rabi_length_ns, "ns"),
        "rabi_drive_amplitude": _quantity(rabi_amplitude, "arb"),
        "drag_beta": _quantity(drag_beta_ns, "ns"),
        "drive_frequency": _quantity(drive_ghz, "GHz"),
        "readout_frequency": _quantity(readout_ghz, "GHz"),
        "readout_power": _quantity(readout_dbm, "dBm"),
        "x_duration": _quantity(4.0, "ns"),
        "x_amplitude": _quantity(0.25, "arb"),
        "quarter_turn_duration": _quantity(16.0, "ns"),
        "quarter_turn_amplitude": _quantity(0.2, "arb"),
        "quarter_turn_sigma": _quantity(4.0, "ns"),
        "readout_duration": _quantity(8.0, "ns"),
        "readout_amplitude": _quantity(0.4, "arb"),
    }


def _two_qubit_gate_row(
    control: str,
    partner: str,
    *,
    control_echo: float,
    partner_echo: float,
    parking_flux: float,
    coupler_amplitude: float,
) -> dict[str, ParameterAtomValue]:
    return {
        "control_qubit": EntityRef(id=control, kind="logical_qubit"),
        "partner_qubit": EntityRef(id=partner, kind="logical_qubit"),
        "gate": "cz",
        "coupler": EntityRef(
            id=f"coupler-{control}-{partner}",
            kind="logical_coupler",
        ),
        "control_echo_amplitude": _quantity(control_echo, "arb"),
        "partner_echo_amplitude": _quantity(partner_echo, "arb"),
        "coupler_parking_flux": _quantity(parking_flux, "arb"),
        "coupler_amplitude": _quantity(coupler_amplitude, "arb"),
        "duration": _quantity(32.0, "ns"),
        "sample_rate_hz": 1_000_000_000.0,
    }


def _quantity(value: float, unit: str) -> Quantity:
    return Quantity(value=value, unit=unit)


__all__ = ["quantum_lab_parameter_snapshot"]
