"""Small calculation helpers used by promoted readout analysis steps."""

from __future__ import annotations

import math
from dataclasses import dataclass

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.results import ComplexQuantity, MeasurementRecord

from quantum_lab_demo.experiments.readout_responses import (
    _frequency_to_ghz,
    _settings_from_config,
)

READOUT_PARAMETER_ID = "readout_frequency"


@dataclass(frozen=True)
class ReadoutFrequencyAnalysisSummary:
    measurement_count: int
    best_point_index: int
    center: Quantity
    minimum_s21: Quantity
    figure_ref: str
    reason: str


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
    minimum_s21 = _s21_observable(
        measurement=best_measurement,
        input_ref=input_ref,
    )
    return ReadoutFrequencyAnalysisSummary(
        measurement_count=len(processed_measurements),
        best_point_index=best_measurement.point_index,
        center=center,
        minimum_s21=minimum_s21,
        figure_ref="analysis:readout-frequency-scan",
        reason=f"Minimum S21 observed at point {best_measurement.point_index}.",
    )


def _process_measurement(
    *,
    measurement: MeasurementRecord,
    configured_readout_frequency_ghz: float,
    readout_power_dbm: float,
    input_ref: str,
) -> MeasurementRecord:
    raw_iq = _raw_complex(
        measurement=measurement,
        observable_id="raw_iq",
        input_ref=input_ref,
    )
    amplitude = round(abs(raw_iq), 12)
    if amplitude <= 0:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_readout_raw_observable",
                    "raw_iq amplitude must be greater than zero",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    phase = round(math.atan2(raw_iq.imag, raw_iq.real), 12)
    frequency = measurement.coordinates.get(READOUT_PARAMETER_ID)
    if not isinstance(frequency, Quantity):
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
            "raw_iq": ComplexQuantity(
                real=raw_iq.real,
                imag=raw_iq.imag,
                unit="ratio",
            ),
            "iq_amplitude": Quantity(value=amplitude, unit="ratio"),
            "iq_phase": Quantity(value=phase, unit="rad"),
            "readout_detuning": Quantity(value=detuning_mhz, unit="MHz"),
            "s21_db": Quantity(value=s21_db, unit="dB"),
        },
        metadata={
            **measurement.metadata,
            "analysis": "readout.frequency.analysis",
            "source_observables": ["raw_iq"],
        },
    )


def _raw_complex(
    *,
    measurement: MeasurementRecord,
    observable_id: str,
    input_ref: str,
) -> complex:
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
    if not isinstance(observable, ComplexQuantity):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_readout_raw_observable",
                    f"readout observable {observable_id} must be scalar complex",
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
    return complex(observable.real, observable.imag)


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
        _s21_observable(measurement=measurement, input_ref=input_ref)
    return min(
        candidates,
        key=lambda measurement: (
            _s21_observable(measurement=measurement, input_ref=input_ref).value,
            measurement.point_index,
        ),
    )


def _s21_observable(*, measurement: MeasurementRecord, input_ref: str) -> Quantity:
    observable = measurement.observables["s21_db"]
    if not isinstance(observable, Quantity) or observable.unit != "dB":
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_readout_s21_observable",
                    "readout s21_db observable must be a scalar dB quantity",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    return observable


def _readout_frequency_parameter(
    *, measurement: MeasurementRecord, input_ref: str
) -> Quantity:
    parameter = measurement.coordinates.get(READOUT_PARAMETER_ID)
    if not isinstance(parameter, Quantity):
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
    "analyze_readout_frequency_measurements",
]
