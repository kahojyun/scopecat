"""Small calculation helpers used by promoted readout analysis steps."""

from __future__ import annotations

import math
from dataclasses import dataclass

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementRecord

from quantum_lab_demo.readout.responses import _frequency_to_ghz, _settings_from_config

READOUT_PARAMETER_ID = "readout_frequency"


@dataclass(frozen=True)
class ReadoutFrequencyAnalysisSummary:
    measurement_count: int
    best_point_index: int
    center: Quantity
    minimum_s21: Quantity
    figure_ref: str
    reason: str


@dataclass(frozen=True)
class ReadoutIQQualityAnalysisSummary:
    measurement_count: int
    visibility: Quantity
    snr: Quantity
    threshold: Quantity
    figure_ref: str


def analyze_readout_frequency_measurements(
    *,
    measurements: list[MeasurementRecord],
    input_ref: str,
    config: ConfigProfileSnapshot,
) -> ReadoutFrequencyAnalysisSummary:
    settings = _settings_from_config(config)
    processed_measurements = [
        _process_measurement(
            measurement=measurement,
            configured_readout_frequency_ghz=settings.readout_frequency_ghz,
            readout_power_dbm=settings.readout_power_dbm,
            input_ref=input_ref,
        )
        for measurement in measurements
    ]
    best_measurement = _minimum_s21_measurement(
        measurements=processed_measurements,
        input_ref=input_ref,
    )
    center = _readout_frequency_parameter(
        measurement=best_measurement,
        input_ref=input_ref,
    )
    minimum_s21 = best_measurement.observables["s21_db"]
    return ReadoutFrequencyAnalysisSummary(
        measurement_count=len(processed_measurements),
        best_point_index=best_measurement.point_index,
        center=center,
        minimum_s21=minimum_s21,
        figure_ref="analysis:readout-frequency-scan",
        reason=f"Minimum S21 observed at point {best_measurement.point_index}.",
    )


def analyze_readout_iq_quality_measurements(
    *,
    run_id: str,
    measurements: list[MeasurementRecord],
    input_ref: str,
) -> ReadoutIQQualityAnalysisSummary:
    del run_id
    summary = _analyze_iq_quality_measurements(
        measurements=measurements,
        input_ref=input_ref,
    )
    return ReadoutIQQualityAnalysisSummary(
        measurement_count=summary.measurement_count,
        visibility=summary.visibility,
        snr=summary.snr,
        threshold=summary.threshold,
        figure_ref="analysis:readout-iq-quality-scatter",
    )


@dataclass(frozen=True)
class _IQQualitySummary:
    measurement_count: int
    visibility: Quantity
    snr: Quantity
    threshold: Quantity


def _process_measurement(
    *,
    measurement: MeasurementRecord,
    configured_readout_frequency_ghz: float,
    readout_power_dbm: float,
    input_ref: str,
) -> MeasurementRecord:
    raw_i = _raw_ratio(
        measurement=measurement,
        observable_id="raw_i",
        input_ref=input_ref,
    )
    raw_q = _raw_ratio(
        measurement=measurement,
        observable_id="raw_q",
        input_ref=input_ref,
    )
    amplitude = round(math.hypot(raw_i, raw_q), 12)
    if amplitude <= 0:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_readout_raw_observable",
                    "raw_i/raw_q amplitude must be greater than zero",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    phase = round(math.atan2(raw_q, raw_i), 12)
    frequency = measurement.coordinates.get(READOUT_PARAMETER_ID)
    if frequency is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_parameter",
                    "readout measurement is missing readout_frequency parameter",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    frequency_ghz = _frequency_to_ghz(frequency)
    detuning_mhz = round(
        (frequency_ghz - configured_readout_frequency_ghz) * 1000,
        12,
    )
    s21_db = round(20 * math.log10(amplitude) - readout_power_dbm, 12)
    return MeasurementRecord(
        run_id=measurement.run_id,
        point_index=measurement.point_index,
        coordinates=measurement.coordinates,
        observables={
            "i": Quantity(value=raw_i, unit="ratio"),
            "q": Quantity(value=raw_q, unit="ratio"),
            "iq_amplitude": Quantity(value=amplitude, unit="ratio"),
            "iq_phase": Quantity(value=phase, unit="rad"),
            "readout_detuning": Quantity(value=detuning_mhz, unit="MHz"),
            "s21_db": Quantity(value=s21_db, unit="dB"),
        },
        metadata={
            **measurement.metadata,
            "analysis": "readout.frequency.analysis",
            "source_observables": ["raw_i", "raw_q"],
        },
    )


def _raw_ratio(
    *,
    measurement: MeasurementRecord,
    observable_id: str,
    input_ref: str,
) -> float:
    observable = measurement.observables.get(observable_id)
    if observable is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_raw_observable",
                    f"readout measurement is missing {observable_id}",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    if observable.unit != "ratio":
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_readout_raw_observable",
                    f"readout observable {observable_id} must use ratio unit",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    return observable.value


def _minimum_s21_measurement(
    *,
    measurements: list[MeasurementRecord],
    input_ref: str,
) -> MeasurementRecord:
    candidates = [
        measurement
        for measurement in measurements
        if measurement.observables.get("s21_db") is not None
    ]
    if not candidates:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_s21_observable",
                    "readout analysis input contains no s21_db observable",
                    input_ref,
                )
            ]
        )
    for measurement in candidates:
        observable = measurement.observables["s21_db"]
        if observable.unit != "dB":
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_readout_s21_observable",
                        "readout s21_db observable must use dB unit",
                        _measurement_path(input_ref, measurement),
                    )
                ]
            )
    return min(
        candidates,
        key=lambda measurement: (
            measurement.observables["s21_db"].value,
            measurement.point_index,
        ),
    )


def _readout_frequency_parameter(
    *, measurement: MeasurementRecord, input_ref: str
) -> Quantity:
    parameter = measurement.coordinates.get(READOUT_PARAMETER_ID)
    if parameter is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_frequency_parameter",
                    "minimum S21 measurement is missing readout_frequency",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    return parameter


def _analyze_iq_quality_measurements(
    *,
    measurements: list[MeasurementRecord],
    input_ref: str,
) -> _IQQualitySummary:
    if not measurements:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "empty_readout_iq_quality_input",
                    "readout IQ quality analysis requires measurements",
                    input_ref,
                )
            ]
        )
    state0 = [
        complex(
            _raw_ratio(
                measurement=measurement,
                observable_id="i0",
                input_ref=input_ref,
            ),
            _raw_ratio(
                measurement=measurement,
                observable_id="q0",
                input_ref=input_ref,
            ),
        )
        for measurement in measurements
    ]
    state1 = [
        complex(
            _raw_ratio(
                measurement=measurement,
                observable_id="i1",
                input_ref=input_ref,
            ),
            _raw_ratio(
                measurement=measurement,
                observable_id="q1",
                input_ref=input_ref,
            ),
        )
        for measurement in measurements
    ]
    center0 = sum(state0, start=0j) / len(state0)
    center1 = sum(state1, start=0j) / len(state1)
    separation = abs(center1 - center0)
    noise = _mean_distance(state0, center0) + _mean_distance(state1, center1)
    snr = separation / max(noise, 1e-12)
    midpoint_projection = (abs(center0) + abs(center1)) / 2.0
    visibility = max(0.0, min(1.0, 1.0 - 1.0 / max(snr, 1.0)))
    return _IQQualitySummary(
        measurement_count=len(measurements),
        visibility=Quantity(value=round(visibility, 12), unit="ratio"),
        snr=Quantity(value=round(snr, 12), unit="ratio"),
        threshold=Quantity(value=round(midpoint_projection, 12), unit="ratio"),
    )


def _mean_distance(values: list[complex], center: complex) -> float:
    return sum(abs(value - center) for value in values) / len(values)


def _measurement_path(input_ref: str, measurement: MeasurementRecord) -> str:
    return f"{input_ref}:point[{measurement.point_index}]"


def _diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "ReadoutFrequencyAnalysisSummary",
    "ReadoutIQQualityAnalysisSummary",
    "analyze_readout_frequency_measurements",
    "analyze_readout_iq_quality_measurements",
]
