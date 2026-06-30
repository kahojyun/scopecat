"""Shared readout response models and deterministic measurement helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from scopecat.instruments.state import ExecutionPoint
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.runner import MeasurementSink


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

    schema_version: str = "quantum_lab_demo.readout_response_model.v0"
    resonance_frequency_ghz: float
    linewidth_mhz: float
    baseline_amplitude: float = 0.92
    dip_depth: float = 0.52
    repeatable_variation_amplitude: float = 0.0
    phase_slope: float = 0.55


@dataclass(frozen=True)
class IQCenter:
    i: float
    q: float


class ReadoutIQResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "quantum_lab_demo.readout_iq_response_model.v0"
    state0_center: list[float] = Field(min_length=2, max_length=2)
    state1_center: list[float] = Field(min_length=2, max_length=2)
    noise_sigma: float = Field(gt=0.0)
    shot_count: int = Field(gt=0)
    deterministic_contamination_rate: float = Field(default=0.0, ge=0.0, le=0.5)
    random_seed: int = 17

    @property
    def state0(self) -> IQCenter:
        return IQCenter(i=self.state0_center[0], q=self.state0_center[1])

    @property
    def state1(self) -> IQCenter:
        return IQCenter(i=self.state1_center[0], q=self.state1_center[1])


def load_readout_response_model(path: Path) -> ReadoutResponseModel:
    return ReadoutResponseModel.model_validate_json(path.read_text())


def load_readout_iq_response_model(path: Path) -> ReadoutIQResponseModel:
    return ReadoutIQResponseModel.model_validate_json(path.read_text())


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
    if config.parameter_build is None:
        return Quantity(value=default_value, unit=default_unit)
    parameter_value = config.parameter_build.get(parameter_value_id)
    if parameter_value is None:
        return Quantity(value=default_value, unit=default_unit)
    return parameter_value.quantity


def _record_raw_measurement(
    *,
    sink: MeasurementSink,
    point: ExecutionPoint,
    settings: ReadoutSettings,
    response_model: ReadoutResponseModel,
    producer_id: str,
    producer_kind: Literal["adapter", "instrument"],
) -> None:
    coordinates = point.coordinates
    readout_frequency = coordinates["readout_frequency"]
    frequency_ghz = _frequency_to_ghz(readout_frequency)
    detuning_mhz = round(
        (frequency_ghz - response_model.resonance_frequency_ghz) * 1000,
        12,
    )

    iq_amplitude = _simulated_iq_amplitude(detuning_mhz, response_model, point.index)
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

    sink.record(
        point_index=point.index,
        coordinates=coordinates,
        observables={
            "raw_i": Quantity(value=i_value, unit="ratio"),
            "raw_q": Quantity(value=q_value, unit="ratio"),
        },
        metadata={
            **_producer_metadata(
                producer_id=producer_id,
                producer_kind=producer_kind,
                anti_corruption=(
                    "offline replay of synthetic S21 scan semantics; "
                    "no hardware connection"
                ),
            ),
            "source": "quantum-lab-demo",
            "sample_reference": "sample-public://readout/frequency-calibration-s21",
            "source_function": "readout frequency response",
            "shot_count": settings.reps,
            "readout_power_dbm": settings.readout_power_dbm,
            "response_model": response_model.schema_version,
            "simulated_resonance_frequency_ghz": (
                response_model.resonance_frequency_ghz
            ),
            "simulated_linewidth_mhz": response_model.linewidth_mhz,
            "demod_frequency_mhz": settings.demod_frequency_mhz,
            "lo_frequency_ghz": lo_frequency_ghz,
            "start_delay_ns": settings.start_delay_ns,
            "z_offset": settings.z_offset,
        },
    )


def _simulated_iq_amplitude(
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


def _record_iq_shot(
    *,
    sink: MeasurementSink,
    point_index: int,
    shot_index: int,
    response_model: ReadoutIQResponseModel,
    producer_id: str,
    producer_kind: Literal["adapter", "instrument"],
) -> None:
    state0_center = _contaminated_center(
        prepared_state=0,
        shot_index=shot_index,
        response_model=response_model,
    )
    state1_center = _contaminated_center(
        prepared_state=1,
        shot_index=shot_index,
        response_model=response_model,
    )
    state0_noise = _normal_pair(
        shot_index=shot_index,
        salt=11,
        sigma=response_model.noise_sigma,
        seed=response_model.random_seed,
    )
    state1_noise = _normal_pair(
        shot_index=shot_index,
        salt=29,
        sigma=response_model.noise_sigma,
        seed=response_model.random_seed,
    )

    sink.record(
        point_index=point_index,
        coordinates={"shot_index": Quantity(value=float(shot_index), unit="count")},
        observables={
            "i0": Quantity(
                value=round(state0_center.i + state0_noise[0], 12), unit="ratio"
            ),
            "q0": Quantity(
                value=round(state0_center.q + state0_noise[1], 12), unit="ratio"
            ),
            "i1": Quantity(
                value=round(state1_center.i + state1_noise[0], 12), unit="ratio"
            ),
            "q1": Quantity(
                value=round(state1_center.q + state1_noise[1], 12), unit="ratio"
            ),
        },
        metadata={
            **_producer_metadata(
                producer_id=producer_id,
                producer_kind=producer_kind,
                anti_corruption=(
                    "offline replay of synthetic IQ scatter semantics; no hardware "
                    "connection"
                ),
            ),
            "source": "quantum-lab-demo",
            "sample_reference": "sample-public://readout/iq-quality",
            "source_function": "readout IQ scatter",
            "shot_index": shot_index,
            "state0_label": "|0>",
            "state1_label": "|1>",
            "response_model": response_model.schema_version,
            "response_shot_count": response_model.shot_count,
            "noise_sigma": response_model.noise_sigma,
            "deterministic_contamination_rate": (
                response_model.deterministic_contamination_rate
            ),
        },
    )


def _producer_metadata(
    *,
    producer_id: str,
    producer_kind: Literal["adapter", "instrument"],
    anti_corruption: str,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "producer_id": producer_id,
        "producer_kind": producer_kind,
    }
    if producer_kind == "adapter":
        metadata["adapter"] = producer_id
        metadata["anti_corruption"] = anti_corruption
        return metadata
    metadata["instrument"] = producer_id
    return metadata


def _contaminated_center(
    *,
    prepared_state: int,
    shot_index: int,
    response_model: ReadoutIQResponseModel,
) -> IQCenter:
    contaminated = (
        _unit_interval(
            shot_index=shot_index,
            salt=prepared_state + 101,
            seed=response_model.random_seed,
        )
        < response_model.deterministic_contamination_rate
    )
    if prepared_state == 0:
        return response_model.state1 if contaminated else response_model.state0
    return response_model.state0 if contaminated else response_model.state1


def _normal_pair(
    *,
    shot_index: int,
    salt: int,
    sigma: float,
    seed: int,
) -> tuple[float, float]:
    u1 = max(
        _unit_interval(shot_index=shot_index, salt=salt, seed=seed),
        1e-12,
    )
    u2 = _unit_interval(shot_index=shot_index, salt=salt + 1, seed=seed)
    radius = sigma * math.sqrt(-2.0 * math.log(u1))
    theta = 2.0 * math.pi * u2
    return radius * math.cos(theta), radius * math.sin(theta)


def _unit_interval(*, shot_index: int, salt: int, seed: int) -> float:
    raw = math.sin((shot_index + 1 + seed * 0.017) * (12.9898 + salt * 78.233))
    scaled = raw * 43758.5453123
    return scaled - math.floor(scaled)


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
    "IQCenter",
    "ReadoutIQResponseModel",
    "ReadoutResponseModel",
    "ReadoutSettings",
    "load_readout_iq_response_model",
    "load_readout_response_model",
]
