"""Shared readout response models and deterministic measurement helpers."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import (
    Quantity,
    ScalarParameterValue,
    TableParameterValue,
)


@dataclass(frozen=True)
class ReadoutSettings:
    readout_frequency_ghz: float
    readout_power_dbm: float
    demod_frequency_mhz: float
    start_delay_ns: float
    phase_offset_rad: float
    reps: int
    z_offset: float


class ReadoutResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "quantum_lab_demo.experiments_response_model.v0"
    resonance_frequency_ghz: float
    linewidth_mhz: float
    baseline_amplitude: float = 0.92
    dip_depth: float = 0.52
    repeatable_variation_amplitude: float = 0.0
    phase_slope: float = 0.55


def settings_from_config(
    config: ConfigProfileSnapshot,
    *,
    qubit: str,
) -> ReadoutSettings:
    return ReadoutSettings(
        readout_frequency_ghz=frequency_to_ghz(
            _qubit_quantity(config, qubit=qubit, column="readout_frequency")
        ),
        readout_power_dbm=_power_to_dbm(
            _qubit_quantity(config, qubit=qubit, column="readout_power")
        ),
        demod_frequency_mhz=100.0,
        start_delay_ns=240.0,
        phase_offset_rad=0.0,
        reps=int(_scalar_quantity(config, "repetitions").value),
        z_offset=0.0,
    )


def _scalar_quantity(
    config: ConfigProfileSnapshot,
    parameter_value_id: str,
) -> Quantity:
    stored = config.parameter_snapshot.get(parameter_value_id)
    if not isinstance(stored, ScalarParameterValue) or not isinstance(
        stored.value, Quantity
    ):
        msg = f"parameter {parameter_value_id!r} must be a quantity"
        raise TypeError(msg)
    return stored.value


def _qubit_quantity(
    config: ConfigProfileSnapshot,
    *,
    qubit: str,
    column: str,
) -> Quantity:
    stored = config.parameter_snapshot.get("qubits")
    if not isinstance(stored, TableParameterValue):
        msg = "parameter 'qubits' must be a table"
        raise TypeError(msg)
    matching_rows = [
        row for row in stored.rows if _entity_id(row.get("qubit")) == qubit
    ]
    if len(matching_rows) != 1:
        msg = f"parameter 'qubits' must contain exactly one row for {qubit!r}"
        raise ValueError(msg)
    value = matching_rows[0].get(column)
    if not isinstance(value, Quantity):
        msg = f"parameter 'qubits'.{column} must be a quantity"
        raise TypeError(msg)
    return value


def _entity_id(value: object) -> str | None:
    if isinstance(value, EntityRef):
        return value.id
    return value if isinstance(value, str) else None


def frequency_to_ghz(quantity: Quantity) -> float:
    value = quantity.value
    unit = quantity.unit
    if unit == "GHz":
        return value
    if unit == "MHz":
        return value / 1000
    if unit == "kHz":
        return value / 1_000_000
    if unit == "Hz":
        return value / 1_000_000_000
    raise ValueError(f"unsupported frequency unit: {unit}")


def _power_to_dbm(quantity: Quantity) -> float:
    unit = quantity.unit
    if unit != "dBm":
        raise ValueError(f"unsupported power unit: {unit}")
    return quantity.value


__all__ = [
    "ReadoutResponseModel",
    "ReadoutSettings",
    "frequency_to_ghz",
    "settings_from_config",
]
