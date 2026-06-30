"""Small calculation helpers used by promoted readout analysis steps."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementRecord

from quantum_lab_demo.readout.frequency_evaluation import (
    _minimum_s21_measurement,
    _readout_frequency_parameter,
)
from quantum_lab_demo.readout.frequency_processing import _process_measurement
from quantum_lab_demo.readout.iq_quality_processing import (
    _analyze_measurements,
    _processing_result,
)
from quantum_lab_demo.readout.responses import _settings_from_config


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
    iq_analysis = _analyze_measurements(measurements=measurements, input_ref=input_ref)
    result = _processing_result(
        run_id=run_id,
        input_ref=input_ref,
        analysis=iq_analysis,
    )
    return ReadoutIQQualityAnalysisSummary(
        measurement_count=result.measurement_count,
        visibility=result.visibility,
        snr=result.snr,
        threshold=result.threshold,
        figure_ref="analysis:readout-iq-quality-scatter",
    )


__all__ = [
    "ReadoutFrequencyAnalysisSummary",
    "ReadoutIQQualityAnalysisSummary",
    "analyze_readout_frequency_measurements",
    "analyze_readout_iq_quality_measurements",
]
