"""Processing for readout-frequency calibration raw I/Q measurements."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import ProcessingJob
from scopecat.models.parameter import Quantity
from scopecat.processing.sdk import (
    ArtifactInputDiagnostics,
    ProcessingContext,
    ProcessingStepResult,
    execute_processing_step,
)
from scopecat.results import MeasurementDatasetInputDiagnostics, MeasurementRecord

from quantum_lab_demo.readout.responses import (
    _frequency_to_ghz,
    _settings_from_config,
)

READOUT_PROCESSING_STEP = "readout-frr-processing"
RAW_MEASUREMENTS_ARTIFACT_ID = "raw-measurements"
MEASUREMENT_DATASET_ARTIFACT_KIND = "measurement_dataset"
PROCESSED_DATA_ARTIFACT_ID = "readout-frr-processed"
PROCESSED_DATA_REF = "artifacts/readout-frr-processed.jsonl"
PROCESSED_RESULT_ARTIFACT_ID = "readout-frr-processing-result"
PROCESSED_RESULT_REF = "artifacts/readout-frr-processing.json"
PROCESSED_SUMMARY_ARTIFACT_ID = "readout-frr-processing-summary"
PROCESSED_SUMMARY_REF = "artifacts/readout-frr-processing.md"
PROCESSING_JOB_REF = "processing/readout-frr-processing.job.json"
PROCESSED_OBSERVABLES = [
    "i",
    "q",
    "iq_amplitude",
    "iq_phase",
    "readout_detuning",
    "s21_db",
]


class ReadoutFrequencyProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "quantum_lab_demo.readout_frequency_processing_result.v0"
    run_id: str
    step: str = READOUT_PROCESSING_STEP
    input_ref: str
    output_ref: str
    measurement_count: int
    processed_observables: list[str]
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def execute_readout_frequency_processing(
    *, run_id: str, workspace: str | Path
) -> tuple[ProcessingJob, ReadoutFrequencyProcessingResult]:
    return execute_processing_step(
        run_id=run_id,
        workspace=workspace,
        step=ReadoutFrequencyProcessingStep(),
    )


@dataclass(frozen=True)
class ReadoutFrequencyProcessingStep:
    step_id: str = READOUT_PROCESSING_STEP

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[ReadoutFrequencyProcessingResult]:
        input_artifact = context.inputs.resolve_artifact(
            selector=RAW_MEASUREMENTS_ARTIFACT_ID,
            expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            diagnostics=ArtifactInputDiagnostics(
                not_found_code="readout_processing_input_not_found",
                invalid_kind_code="readout_processing_input_kind_unsupported",
                path_escape_code="readout_processing_input_path_escape",
                not_found_message="readout processing input artifact not found",
                invalid_kind_message=(
                    "readout processing supports measurement_dataset only"
                ),
                path_escape_message=(
                    "readout processing input selector escapes run directory"
                ),
                diagnostic_path="input",
            ),
        )
        dataset = context.inputs.read_measurement_dataset(
            input_artifact,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="missing_readout_processing_input",
                empty_code="empty_readout_processing_input",
                invalid_code="invalid_readout_processing_input",
                missing_schema_code="missing_readout_processing_input_schema",
                invalid_schema_code="invalid_readout_processing_input_schema",
                noun="readout processing input",
                diagnostic_path=input_artifact.ref,
            ),
        )
        measurements = dataset.records
        settings = _settings_from_config(context.config)
        processed_measurements = [
            _process_measurement(
                measurement=measurement,
                configured_readout_frequency_ghz=settings.readout_frequency_ghz,
                readout_power_dbm=settings.readout_power_dbm,
                input_ref=input_artifact.ref,
            )
            for measurement in measurements
        ]
        result = ReadoutFrequencyProcessingResult(
            run_id=context.run_id,
            input_ref=input_artifact.ref,
            output_ref=PROCESSED_DATA_REF,
            measurement_count=len(processed_measurements),
            processed_observables=PROCESSED_OBSERVABLES,
        )
        context.artifacts.write_measurement_dataset(
            id=PROCESSED_DATA_ARTIFACT_ID,
            filename=_artifact_filename(PROCESSED_DATA_REF),
            dataset_role="derived",
            records=processed_measurements,
            source_step=READOUT_PROCESSING_STEP,
            source_artifact_ids=[input_artifact.artifact_id],
        )
        context.artifacts.write_model(
            id=PROCESSED_RESULT_ARTIFACT_ID,
            kind="readout_processing_result",
            filename=_artifact_filename(PROCESSED_RESULT_REF),
            model=result,
            media_type="application/json",
        )
        context.artifacts.write_text(
            id=PROCESSED_SUMMARY_ARTIFACT_ID,
            kind="summary",
            filename=_artifact_filename(PROCESSED_SUMMARY_REF),
            content=render_readout_processing_summary(result),
            media_type="text/markdown",
        )
        return ProcessingStepResult(
            result=result,
            job_id=READOUT_PROCESSING_STEP,
            job_ref=PROCESSING_JOB_REF,
        )


def render_readout_processing_summary(result: ReadoutFrequencyProcessingResult) -> str:
    lines = [
        "# Readout Frequency Processing",
        "",
        f"- Run ID: {result.run_id}",
        f"- Step: {result.step}",
        f"- Input: {result.input_ref}",
        f"- Output: {result.output_ref}",
        f"- Measurements: {result.measurement_count}",
        "",
        "## Observables",
        "",
    ]
    lines.extend(f"- {observable}" for observable in result.processed_observables)
    return "\n".join(lines) + "\n"


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
    frequency = measurement.coordinates.get("readout_frequency")
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
            "processing": READOUT_PROCESSING_STEP,
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


def _measurement_path(input_ref: str, measurement: MeasurementRecord) -> str:
    return f"{input_ref}:point[{measurement.point_index}]"


def _artifact_filename(ref: str) -> str:
    return PurePosixPath(ref).name


def _diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
