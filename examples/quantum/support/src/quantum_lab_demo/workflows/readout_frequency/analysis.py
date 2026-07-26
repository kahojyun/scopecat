"""Readout-frequency fit and reusable analysis step."""

from __future__ import annotations

import math
from dataclasses import dataclass

import scopecat as sc
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.results import ComplexQuantity, MeasurementRecord
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from scopecat.runs.access import dataset_storage_ref
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)

from quantum_lab_demo.virtual_lab.responses.readout_frequency import (
    frequency_to_ghz,
    settings_from_config,
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
    qubit: str,
) -> ReadoutFrequencyAnalysisSummary:
    settings = settings_from_config(config, qubit=qubit)
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


@sc.analysis_step(id="readout.frequency.analysis")
def readout_frequency_analysis(
    context: sc.AnalysisContext,
    *,
    qubit: str,
) -> sc.Analysis:
    """Fit one run and propose its selected readout frequency."""

    raw = context.data.measurements()
    summary = analyze_readout_frequency_measurements(
        measurements=raw.dataset.records,
        input_ref=dataset_storage_ref(raw.dataset_entry),
        config=context.config,
        qubit=qubit,
    )
    return (
        context.result("readout frequency analysis")
        .input(
            raw.dataset_entry.id,
            title="raw measurements",
            expected_kind="measurement_dataset",
        )
        .table(
            [
                {
                    "measurement_count": summary.measurement_count,
                    "best_point_index": summary.best_point_index,
                    "center": summary.center.value,
                    "unit": summary.center.unit,
                    "minimum_s21": summary.minimum_s21.value,
                    "minimum_s21_unit": summary.minimum_s21.unit,
                    "figure_ref": summary.figure_ref,
                }
            ],
            title="fit summary",
        )
        .figure(
            {
                "kind": "line",
                "x": "readout_frequency",
                "y": "s21_db",
                "source_dataset": raw.dataset_entry.id,
            },
            title="frequency scan",
        )
        .propose(
            READOUT_PARAMETER_ID,
            sc.update_parameter_rows(
                "qubits",
                key={"qubit": qubit},
                values={READOUT_PARAMETER_ID: summary.center},
            ),
            reason=summary.reason,
            confidence=1.0,
        )
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
        raise CheckFailed(
            [
                _problem(
                    "invalid_readout_raw_observable",
                    "raw_iq amplitude must be greater than zero",
                    input_ref=input_ref,
                    measurement=measurement,
                )
            ]
        )
    phase = round(math.atan2(raw_iq.imag, raw_iq.real), 12)
    frequency = measurement.coordinates.get(READOUT_PARAMETER_ID)
    if not isinstance(frequency, Quantity):
        raise CheckFailed(
            [
                _problem(
                    "missing_readout_parameter",
                    "readout measurement is missing readout_frequency parameter",
                    input_ref=input_ref,
                    measurement=measurement,
                )
            ]
        )
    frequency_ghz = frequency_to_ghz(frequency)
    detuning_mhz = round(
        (frequency_ghz - configured_readout_frequency_ghz) * 1000,
        12,
    )
    s21_db = round(20 * math.log10(amplitude) - readout_power_dbm, 12)
    return MeasurementRecord(
        run_id=measurement.run_id,
        logical_point_id=measurement.logical_point_id,
        point_index=measurement.point_index,
        instrument_ids=measurement.instrument_ids,
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
        raise CheckFailed(
            [
                _problem(
                    "missing_readout_raw_observable",
                    f"readout measurement is missing {observable_id}",
                    input_ref=input_ref,
                    measurement=measurement,
                )
            ]
        )
    if not isinstance(observable, ComplexQuantity):
        raise CheckFailed(
            [
                _problem(
                    "invalid_readout_raw_observable",
                    f"readout observable {observable_id} must be scalar complex",
                    input_ref=input_ref,
                    measurement=measurement,
                )
            ]
        )
    if observable.unit != "ratio":
        raise CheckFailed(
            [
                _problem(
                    "invalid_readout_raw_observable",
                    f"readout observable {observable_id} must use ratio unit",
                    input_ref=input_ref,
                    measurement=measurement,
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
        raise CheckFailed(
            [
                _problem(
                    "missing_readout_s21_observable",
                    "readout analysis input contains no s21_db observable",
                    input_ref=input_ref,
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
        raise CheckFailed(
            [
                _problem(
                    "invalid_readout_s21_observable",
                    "readout s21_db observable must be a scalar dB quantity",
                    input_ref=input_ref,
                    measurement=measurement,
                )
            ]
        )
    return observable


def _readout_frequency_parameter(
    *, measurement: MeasurementRecord, input_ref: str
) -> Quantity:
    parameter = measurement.coordinates.get(READOUT_PARAMETER_ID)
    if not isinstance(parameter, Quantity):
        raise CheckFailed(
            [
                _problem(
                    "missing_readout_frequency_parameter",
                    "minimum S21 measurement is missing readout_frequency",
                    input_ref=input_ref,
                    measurement=measurement,
                )
            ]
        )
    return parameter


def _problem(
    code: str,
    message: str,
    *,
    input_ref: str,
    measurement: MeasurementRecord | None = None,
) -> Problem:
    path: tuple[str | int, ...] = (input_ref,)
    if measurement is not None:
        path = (*path, "points", measurement.point_index)
    return problem(
        code,
        message,
        phase=ProblemPhase.ANALYSIS,
        location=model_location("analysis_input", *path),
        details={"input_ref": input_ref},
    )


__all__ = [
    "ReadoutFrequencyAnalysisSummary",
    "analyze_readout_frequency_measurements",
    "readout_frequency_analysis",
]
