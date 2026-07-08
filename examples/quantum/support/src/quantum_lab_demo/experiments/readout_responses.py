"""Shared readout response models and deterministic measurement helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import Quantity
from scopecat.results import ComplexQuantity


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


def _settings_from_config(config: ConfigProfileSnapshot) -> ReadoutSettings:
    return ReadoutSettings(
        readout_frequency_ghz=_frequency_to_ghz(
            _quantity(config, "readout_frequency", 5.95, "GHz")
        ),
        readout_power_dbm=_power_to_dbm(
            _quantity(config, "readout_power", -27.0, "dBm")
        ),
        demod_frequency_mhz=_frequency_to_mhz(
            _quantity(config, "demod_frequency", 100.0, "MHz")
        ),
        start_delay_ns=_time_to_ns(_quantity(config, "start_delay", 240.0, "ns")),
        phase_offset_rad=_phase_to_rad(_quantity(config, "readout_phase", 0.0, "rad")),
        reps=int(_quantity(config, "repetitions", 600.0, "count").value),
        z_offset=_quantity(config, "readout_z_offset", 0.0, "arb").value,
    )


def _quantity(
    config: ConfigProfileSnapshot,
    parameter_value_id: str,
    default_value: float,
    default_unit: str,
) -> Quantity:
    parameter_value = build_config_parameters(config).get(parameter_value_id)
    if parameter_value is None:
        return Quantity(value=default_value, unit=default_unit)
    return parameter_value.quantity


def _record_raw_measurement(
    *,
    point_index: int,
    settings: ReadoutSettings,
    response_model: ReadoutResponseModel,
    producer_id: str,
) -> dict[str, ComplexQuantity]:
    del producer_id
    frequency_ghz = settings.readout_frequency_ghz
    detuning_mhz = round(
        (frequency_ghz - response_model.resonance_frequency_ghz) * 1000,
        12,
    )

    iq_amplitude = _modeled_iq_amplitude(detuning_mhz, response_model, point_index)
    iq_phase = round(
        settings.phase_offset_rad
        + response_model.phase_slope
        * math.atan2(
            detuning_mhz,
            response_model.linewidth_mhz,
        ),
        12,
    )
    i_value = round(iq_amplitude * math.cos(iq_phase), 12)
    q_value = round(iq_amplitude * math.sin(iq_phase), 12)
    lo_frequency_ghz = round(
        frequency_ghz - settings.demod_frequency_mhz / 1000,
        12,
    )

    del lo_frequency_ghz
    return {"raw_iq": ComplexQuantity(real=i_value, imag=q_value, unit="ratio")}


def _modeled_iq_amplitude(
    detuning_mhz: float,
    response_model: ReadoutResponseModel,
    point_index: int,
) -> float:
    dip = response_model.dip_depth / (
        1.0 + (detuning_mhz / response_model.linewidth_mhz) ** 2
    )
    small_repeatable_variation = response_model.repeatable_variation_amplitude * (
        math.sin(point_index + 1)
    )
    return round(
        response_model.baseline_amplitude - dip + small_repeatable_variation,
        12,
    )


def _frequency_to_ghz(quantity: Quantity) -> float:
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


def _frequency_to_mhz(quantity: Quantity) -> float:
    value = quantity.value
    unit = quantity.unit
    if unit == "GHz":
        return value * 1000
    if unit == "MHz":
        return value
    if unit == "kHz":
        return value / 1000
    if unit == "Hz":
        return value / 1_000_000
    raise ValueError(f"unsupported frequency unit: {unit}")


def _time_to_ns(quantity: Quantity) -> float:
    value = quantity.value
    unit = quantity.unit
    if unit == "s":
        return value * 1_000_000_000
    if unit == "ms":
        return value * 1_000_000
    if unit == "us":
        return value * 1000
    if unit == "ns":
        return value
    raise ValueError(f"unsupported time unit: {unit}")


def _power_to_dbm(quantity: Quantity) -> float:
    unit = quantity.unit
    if unit != "dBm":
        raise ValueError(f"unsupported power unit: {unit}")
    return quantity.value


def _phase_to_rad(quantity: Quantity) -> float:
    value = quantity.value
    unit = quantity.unit
    if unit == "rad":
        return value
    if unit == "deg":
        return value * math.pi / 180
    raise ValueError(f"unsupported phase unit: {unit}")


__all__ = [
    "ReadoutResponseModel",
    "ReadoutSettings",
]
