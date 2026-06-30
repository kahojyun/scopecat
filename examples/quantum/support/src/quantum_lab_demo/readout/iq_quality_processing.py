"""Shot-level readout IQ quality processing diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from itertools import pairwise
from pathlib import Path, PurePosixPath

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import ProcessingJob
from scopecat.models.data_artifact import (
    DataArrayDimension,
    DataArraySchema,
    DataArrayVariable,
    DataColumn,
    DataTableSchema,
)
from scopecat.models.parameter import Quantity
from scopecat.processing.sdk import (
    ArtifactInputDiagnostics,
    ProcessingContext,
    ProcessingJobArtifact,
    ProcessingStepResult,
    execute_processing_step,
)
from scopecat.results import MeasurementDatasetInputDiagnostics, MeasurementRecord

from quantum_lab_demo.readout._plotting import plt

RAW_MEASUREMENTS_ARTIFACT_ID = "raw-measurements"
MEASUREMENT_DATASET_ARTIFACT_KIND = "measurement_dataset"
READOUT_IQ_QUALITY_STEP = "readout-iq-quality-processing"
READOUT_IQ_PROCESSED_ARTIFACT_ID = "readout-iq-quality-processed"
READOUT_IQ_PROCESSED_REF = "artifacts/readout-iq-quality-processed.jsonl"
READOUT_IQ_RESULT_ARTIFACT_ID = "readout-iq-quality-processing-result"
READOUT_IQ_RESULT_REF = "artifacts/readout-iq-quality-processing.json"
READOUT_IQ_METRICS_ARTIFACT_ID = "readout-iq-quality-metrics"
READOUT_IQ_METRICS_REF = "artifacts/readout-iq-quality-metrics.json"
READOUT_IQ_MATRIX_ARTIFACT_ID = "readout-iq-quality-readout-matrix"
READOUT_IQ_MATRIX_REF = "artifacts/readout-iq-quality-readout-matrix.json"
READOUT_IQ_SUMMARY_ARTIFACT_ID = "readout-iq-quality-processing-summary"
READOUT_IQ_SUMMARY_REF = "artifacts/readout-iq-quality-processing.md"
READOUT_IQ_FIGURE_ARTIFACT_ID = "readout-iq-quality-processing-figure"
READOUT_IQ_FIGURE_REF = "artifacts/readout-iq-quality-processing.png"
READOUT_IQ_JOB_ARTIFACT_ID = "readout-iq-quality-processing-job"
READOUT_IQ_JOB_REF = "processing/readout-iq-quality-processing.job.json"
RAW_IQ_OBSERVABLES = ("i0", "q0", "i1", "q1")


@dataclass(frozen=True)
class _IQShot:
    measurement: MeasurementRecord
    i0: float
    q0: float
    i1: float
    q1: float


@dataclass(frozen=True)
class _IQQualityAnalysis:
    shots: list[_IQShot]
    state0_rotated: list[complex]
    state1_rotated: list[complex]
    rotation_angle: float
    threshold: float
    p00: float
    p11: float
    visibility: float
    snr: float
    separation_error: float
    readout_matrix: list[list[float]]
    center0: tuple[float, float]
    center1: tuple[float, float]


class ReadoutIQQualityProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "quantum_lab_demo.readout_iq_quality_processing_result.v0"
    run_id: str
    step: str = READOUT_IQ_QUALITY_STEP
    input_ref: str
    output_ref: str
    figure_ref: str
    measurement_count: int
    threshold: Quantity
    rotation_angle: Quantity
    p00: Quantity
    p11: Quantity
    visibility: Quantity
    snr: Quantity
    separation_error: Quantity
    readout_matrix: list[list[float]]
    center0: list[Quantity]
    center1: list[Quantity]
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def execute_readout_iq_quality_processing(
    *, run_id: str, workspace: str | Path
) -> tuple[ProcessingJob, ReadoutIQQualityProcessingResult]:
    return execute_processing_step(
        run_id=run_id,
        workspace=workspace,
        step=ReadoutIQQualityProcessingStep(),
    )


@dataclass(frozen=True)
class ReadoutIQQualityProcessingStep:
    step_id: str = READOUT_IQ_QUALITY_STEP

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[ReadoutIQQualityProcessingResult]:
        input_artifact = context.inputs.resolve_artifact(
            selector=RAW_MEASUREMENTS_ARTIFACT_ID,
            expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            diagnostics=ArtifactInputDiagnostics(
                not_found_code="readout_iq_quality_input_not_found",
                invalid_kind_code="readout_iq_quality_input_kind_unsupported",
                path_escape_code="readout_iq_quality_input_path_escape",
                not_found_message="readout IQ quality input artifact not found",
                invalid_kind_message=(
                    "readout IQ quality supports measurement_dataset only"
                ),
                path_escape_message=(
                    "readout IQ quality input selector escapes run directory"
                ),
                diagnostic_path="input",
            ),
        )
        dataset = context.inputs.read_measurement_dataset(
            input_artifact,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="missing_readout_iq_quality_input",
                empty_code="empty_readout_iq_quality_input",
                invalid_code="invalid_readout_iq_quality_input",
                missing_schema_code="missing_readout_iq_quality_input_schema",
                invalid_schema_code="invalid_readout_iq_quality_input_schema",
                noun="readout IQ quality input",
                diagnostic_path=input_artifact.ref,
            ),
        )
        measurements = dataset.records
        analysis = _analyze_measurements(
            measurements=measurements,
            input_ref=input_artifact.ref,
        )
        processed_measurements = _processed_measurements(
            run_id=context.run_id,
            analysis=analysis,
            input_ref=input_artifact.ref,
        )
        result = _processing_result(
            run_id=context.run_id,
            input_ref=input_artifact.ref,
            analysis=analysis,
        )
        context.artifacts.write_measurement_dataset(
            id=READOUT_IQ_PROCESSED_ARTIFACT_ID,
            filename=_artifact_filename(READOUT_IQ_PROCESSED_REF),
            dataset_role="derived",
            records=processed_measurements,
            source_step=READOUT_IQ_QUALITY_STEP,
            source_artifact_ids=[input_artifact.artifact_id],
        )
        context.artifacts.write_model(
            id=READOUT_IQ_RESULT_ARTIFACT_ID,
            kind="readout_iq_quality_processing_result",
            filename=_artifact_filename(READOUT_IQ_RESULT_REF),
            model=result,
            media_type="application/json",
        )
        context.artifacts.write_data_table(
            id=READOUT_IQ_METRICS_ARTIFACT_ID,
            filename=_artifact_filename(READOUT_IQ_METRICS_REF),
            schema=_metrics_table_schema(),
            rows=[_metrics_table_row(result)],
            source_step=READOUT_IQ_QUALITY_STEP,
            source_artifact_ids=[input_artifact.artifact_id],
        )
        context.artifacts.write_data_array(
            id=READOUT_IQ_MATRIX_ARTIFACT_ID,
            filename=_artifact_filename(READOUT_IQ_MATRIX_REF),
            schema=_readout_matrix_schema(),
            variables={
                "readout_probability": _prepared_assigned_readout_matrix(result)
            },
            source_step=READOUT_IQ_QUALITY_STEP,
            source_artifact_ids=[input_artifact.artifact_id],
        )
        context.artifacts.write_text(
            id=READOUT_IQ_SUMMARY_ARTIFACT_ID,
            kind="summary",
            filename=_artifact_filename(READOUT_IQ_SUMMARY_REF),
            content=render_readout_iq_quality_summary(result),
            media_type="text/markdown",
        )
        context.artifacts.write_bytes(
            id=READOUT_IQ_FIGURE_ARTIFACT_ID,
            kind="plot",
            filename=_artifact_filename(READOUT_IQ_FIGURE_REF),
            content=_render_iq_quality_figure(analysis=analysis),
            media_type="image/png",
            metadata={"source_step": READOUT_IQ_QUALITY_STEP},
        )
        return ProcessingStepResult(
            result=result,
            job_id=READOUT_IQ_QUALITY_STEP,
            job_ref=READOUT_IQ_JOB_REF,
            job_artifact=ProcessingJobArtifact(id=READOUT_IQ_JOB_ARTIFACT_ID),
        )


def render_readout_iq_quality_summary(
    result: ReadoutIQQualityProcessingResult,
) -> str:
    lines = [
        "# Readout IQ Quality Processing",
        "",
        f"- Run ID: {result.run_id}",
        f"- Step: {result.step}",
        f"- Input: {result.input_ref}",
        f"- Output: {result.output_ref}",
        f"- Figure: {result.figure_ref}",
        f"- Measurements: {result.measurement_count}",
        f"- Threshold: {result.threshold.value} {result.threshold.unit}",
        f"- Rotation angle: {result.rotation_angle.value} {result.rotation_angle.unit}",
        f"- p00: {result.p00.value} {result.p00.unit}",
        f"- p11: {result.p11.value} {result.p11.unit}",
        f"- Visibility: {result.visibility.value} {result.visibility.unit}",
        f"- SNR: {result.snr.value} {result.snr.unit}",
        f"- Separation error: {result.separation_error.value} "
        f"{result.separation_error.unit}",
        "",
    ]
    return "\n".join(lines) + "\n"


def _analyze_measurements(
    *, measurements: list[MeasurementRecord], input_ref: str
) -> _IQQualityAnalysis:
    if len(measurements) < 2:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "insufficient_readout_iq_input",
                    "readout IQ quality processing requires at least two shots",
                    input_ref,
                )
            ]
        )
    shots = [
        _iq_shot(measurement=measurement, input_ref=input_ref)
        for measurement in measurements
    ]
    center0 = (
        sum(shot.i0 for shot in shots) / len(shots),
        sum(shot.q0 for shot in shots) / len(shots),
    )
    center1 = (
        sum(shot.i1 for shot in shots) / len(shots),
        sum(shot.q1 for shot in shots) / len(shots),
    )
    separation = complex(center1[0] - center0[0], center1[1] - center0[1])
    if abs(separation) <= 1e-12:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "insufficient_readout_iq_state_separation",
                    "readout IQ centers are not separated enough to classify",
                    input_ref,
                )
            ]
        )

    rotation_angle = -math.atan2(separation.imag, separation.real)
    rotation = complex(math.cos(rotation_angle), math.sin(rotation_angle))
    state0_rotated = [complex(shot.i0, shot.q0) * rotation for shot in shots]
    state1_rotated = [complex(shot.i1, shot.q1) * rotation for shot in shots]
    if _mean([value.real for value in state0_rotated]) > _mean(
        [value.real for value in state1_rotated]
    ):
        state0_rotated = [-value for value in state0_rotated]
        state1_rotated = [-value for value in state1_rotated]
        rotation_angle = _normalize_angle(rotation_angle + math.pi)

    threshold, p00, p11 = _best_threshold(
        state0_values=[value.real for value in state0_rotated],
        state1_values=[value.real for value in state1_rotated],
    )
    std0 = _std([value.real for value in state0_rotated])
    std1 = _std([value.real for value in state1_rotated])
    denominator = std0**2 + std1**2
    if denominator <= 1e-18:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "insufficient_readout_iq_input",
                    "readout IQ rotated distributions have zero variance",
                    input_ref,
                )
            ]
        )
    state0_mean = _mean([value.real for value in state0_rotated])
    state1_mean = _mean([value.real for value in state1_rotated])
    snr = (state1_mean - state0_mean) ** 2 / denominator
    p01 = 1.0 - p00
    p10 = 1.0 - p11
    return _IQQualityAnalysis(
        shots=shots,
        state0_rotated=state0_rotated,
        state1_rotated=state1_rotated,
        rotation_angle=round(_normalize_angle(rotation_angle), 12),
        threshold=round(threshold, 12),
        p00=round(p00, 12),
        p11=round(p11, 12),
        visibility=round(p00 + p11 - 1.0, 12),
        snr=round(snr, 12),
        separation_error=round(0.5 * math.erfc(math.sqrt(snr) / 2.0), 12),
        readout_matrix=[
            [round(p00, 12), round(p10, 12)],
            [round(p01, 12), round(p11, 12)],
        ],
        center0=(round(center0[0], 12), round(center0[1], 12)),
        center1=(round(center1[0], 12), round(center1[1], 12)),
    )


def _iq_shot(*, measurement: MeasurementRecord, input_ref: str) -> _IQShot:
    return _IQShot(
        measurement=measurement,
        i0=_raw_iq_value(
            measurement=measurement,
            observable_id="i0",
            input_ref=input_ref,
        ),
        q0=_raw_iq_value(
            measurement=measurement,
            observable_id="q0",
            input_ref=input_ref,
        ),
        i1=_raw_iq_value(
            measurement=measurement,
            observable_id="i1",
            input_ref=input_ref,
        ),
        q1=_raw_iq_value(
            measurement=measurement,
            observable_id="q1",
            input_ref=input_ref,
        ),
    )


def _raw_iq_value(
    *, measurement: MeasurementRecord, observable_id: str, input_ref: str
) -> float:
    observable = measurement.observables.get(observable_id)
    if observable is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_iq_observable",
                    f"readout IQ measurement is missing {observable_id}",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    if observable.unit != "ratio":
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_readout_iq_observable",
                    f"readout IQ observable {observable_id} must use ratio unit",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    return observable.value


def _processed_measurements(
    *,
    run_id: str,
    analysis: _IQQualityAnalysis,
    input_ref: str,
) -> list[MeasurementRecord]:
    processed: list[MeasurementRecord] = []
    for shot, state0, state1 in zip(
        analysis.shots,
        analysis.state0_rotated,
        analysis.state1_rotated,
        strict=True,
    ):
        state0_assignment = 0 if state0.real <= analysis.threshold else 1
        state1_assignment = 0 if state1.real <= analysis.threshold else 1
        processed.append(
            MeasurementRecord(
                run_id=run_id,
                point_index=shot.measurement.point_index,
                coordinates=shot.measurement.coordinates,
                observables={
                    "state0_rotated_i": Quantity(
                        value=round(state0.real, 12),
                        unit="ratio",
                    ),
                    "state0_rotated_q": Quantity(
                        value=round(state0.imag, 12),
                        unit="ratio",
                    ),
                    "state1_rotated_i": Quantity(
                        value=round(state1.real, 12),
                        unit="ratio",
                    ),
                    "state1_rotated_q": Quantity(
                        value=round(state1.imag, 12),
                        unit="ratio",
                    ),
                    "state0_assignment": Quantity(
                        value=state0_assignment,
                        unit="count",
                    ),
                    "state1_assignment": Quantity(
                        value=state1_assignment,
                        unit="count",
                    ),
                },
                metadata={
                    **shot.measurement.metadata,
                    "processing": READOUT_IQ_QUALITY_STEP,
                    "source_ref": input_ref,
                    "source_observables": list(RAW_IQ_OBSERVABLES),
                    "threshold": analysis.threshold,
                    "rotation_angle_rad": analysis.rotation_angle,
                },
            )
        )
    return processed


def _processing_result(
    *,
    run_id: str,
    input_ref: str,
    analysis: _IQQualityAnalysis,
) -> ReadoutIQQualityProcessingResult:
    return ReadoutIQQualityProcessingResult(
        run_id=run_id,
        input_ref=input_ref,
        output_ref=READOUT_IQ_PROCESSED_REF,
        figure_ref=READOUT_IQ_FIGURE_REF,
        measurement_count=len(analysis.shots),
        threshold=Quantity(value=analysis.threshold, unit="ratio"),
        rotation_angle=Quantity(value=analysis.rotation_angle, unit="rad"),
        p00=Quantity(value=analysis.p00, unit="ratio"),
        p11=Quantity(value=analysis.p11, unit="ratio"),
        visibility=Quantity(value=analysis.visibility, unit="ratio"),
        snr=Quantity(value=analysis.snr, unit="ratio"),
        separation_error=Quantity(value=analysis.separation_error, unit="ratio"),
        readout_matrix=analysis.readout_matrix,
        center0=[
            Quantity(value=analysis.center0[0], unit="ratio"),
            Quantity(value=analysis.center0[1], unit="ratio"),
        ],
        center1=[
            Quantity(value=analysis.center1[0], unit="ratio"),
            Quantity(value=analysis.center1[1], unit="ratio"),
        ],
    )


def _metrics_table_schema() -> DataTableSchema:
    return DataTableSchema(
        columns=[
            DataColumn(
                id="threshold",
                role="observable",
                dtype="float64",
                unit="ratio",
            ),
            DataColumn(id="p00", role="observable", dtype="float64", unit="ratio"),
            DataColumn(id="p11", role="observable", dtype="float64", unit="ratio"),
            DataColumn(
                id="visibility",
                role="observable",
                dtype="float64",
                unit="ratio",
            ),
            DataColumn(
                id="snr",
                role="observable",
                dtype="float64",
                unit="ratio",
            ),
            DataColumn(
                id="separation_error",
                role="observable",
                dtype="float64",
                unit="ratio",
            ),
        ],
        metadata={"category": "readout_iq_quality"},
    )


def _metrics_table_row(
    result: ReadoutIQQualityProcessingResult,
) -> dict[str, float]:
    return {
        "threshold": result.threshold.value,
        "p00": result.p00.value,
        "p11": result.p11.value,
        "visibility": result.visibility.value,
        "snr": result.snr.value,
        "separation_error": result.separation_error.value,
    }


def _readout_matrix_schema() -> DataArraySchema:
    return DataArraySchema(
        dimensions=[
            DataArrayDimension(
                id="prepared_state",
                kind="state",
                size=2,
                metadata={"labels": ["0", "1"]},
            ),
            DataArrayDimension(
                id="assigned_state",
                kind="state",
                size=2,
                metadata={"labels": ["0", "1"]},
            ),
        ],
        variables=[
            DataArrayVariable(
                id="readout_probability",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["prepared_state", "assigned_state"],
                shape=[2, 2],
            )
        ],
        primary_variables=["readout_probability"],
        metadata={"category": "readout_iq_quality"},
    )


def _prepared_assigned_readout_matrix(
    result: ReadoutIQQualityProcessingResult,
) -> list[list[float]]:
    return [
        [result.readout_matrix[0][0], result.readout_matrix[1][0]],
        [result.readout_matrix[0][1], result.readout_matrix[1][1]],
    ]


def _best_threshold(
    *, state0_values: list[float], state1_values: list[float]
) -> tuple[float, float, float]:
    values = sorted({*state0_values, *state1_values})
    candidates = [(left + right) / 2.0 for left, right in pairwise(values)]
    candidates.insert(0, values[0] - 1e-9)
    candidates.append(values[-1] + 1e-9)
    best_threshold = candidates[0]
    best_p00 = 0.0
    best_p11 = 0.0
    best_visibility = -1.0
    for threshold in candidates:
        p00 = sum(value <= threshold for value in state0_values) / len(state0_values)
        p11 = sum(value > threshold for value in state1_values) / len(state1_values)
        visibility = p00 + p11 - 1.0
        if visibility > best_visibility:
            best_threshold = threshold
            best_p00 = p00
            best_p11 = p11
            best_visibility = visibility
    return best_threshold, best_p00, best_p11


def _render_iq_quality_figure(*, analysis: _IQQualityAnalysis) -> bytes:
    state0_raw_i = [shot.i0 for shot in analysis.shots]
    state0_raw_q = [shot.q0 for shot in analysis.shots]
    state1_raw_i = [shot.i1 for shot in analysis.shots]
    state1_raw_q = [shot.q1 for shot in analysis.shots]
    state0_rot_i = [value.real for value in analysis.state0_rotated]
    state0_rot_q = [value.imag for value in analysis.state0_rotated]
    state1_rot_i = [value.real for value in analysis.state1_rotated]
    state1_rot_q = [value.imag for value in analysis.state1_rotated]

    figure, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    ((raw_axis, rotated_axis), (hist_axis, matrix_axis)) = axes

    raw_axis.scatter(state0_raw_i, state0_raw_q, s=12, alpha=0.55, label="|0>")
    raw_axis.scatter(state1_raw_i, state1_raw_q, s=12, alpha=0.55, label="|1>")
    raw_axis.set_title("Raw IQ")
    raw_axis.set_xlabel("I (ratio)")
    raw_axis.set_ylabel("Q (ratio)")
    raw_axis.set_aspect("equal", adjustable="datalim")
    raw_axis.legend(loc="best")

    rotated_axis.scatter(state0_rot_i, state0_rot_q, s=12, alpha=0.55, label="|0>")
    rotated_axis.scatter(state1_rot_i, state1_rot_q, s=12, alpha=0.55, label="|1>")
    rotated_axis.axvline(analysis.threshold, color="black", linestyle="--")
    rotated_axis.set_title("Rotated IQ")
    rotated_axis.set_xlabel("I' (ratio)")
    rotated_axis.set_ylabel("Q' (ratio)")
    rotated_axis.set_aspect("equal", adjustable="datalim")

    hist_axis.hist(state0_rot_i, bins=40, alpha=0.55, label="|0>")
    hist_axis.hist(state1_rot_i, bins=40, alpha=0.55, label="|1>")
    hist_axis.axvline(analysis.threshold, color="black", linestyle="--")
    hist_axis.set_title("Rotated I histogram")
    hist_axis.set_xlabel("I' (ratio)")
    hist_axis.set_ylabel("Counts")
    hist_axis.legend(loc="best")

    matrix = np.asarray(analysis.readout_matrix)
    image = matrix_axis.imshow(matrix, vmin=0.0, vmax=1.0, cmap="Blues")
    matrix_axis.set_title("Readout matrix")
    matrix_axis.set_xticks([0, 1], labels=["prep |0>", "prep |1>"])
    matrix_axis.set_yticks([0, 1], labels=["assign |0>", "assign |1>"])
    for row in range(2):
        for column in range(2):
            matrix_axis.text(
                column,
                row,
                f"{matrix[row, column]:.3f}",
                ha="center",
                va="center",
                color="black",
            )
    figure.colorbar(image, ax=matrix_axis, fraction=0.046, pad=0.04)

    for axis in (raw_axis, rotated_axis, hist_axis):
        axis.grid(True, alpha=0.25)

    output = BytesIO()
    figure.savefig(output, format="png", dpi=160)
    plt.close(figure)
    return output.getvalue()


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _normalize_angle(angle: float) -> float:
    while angle <= -math.pi:
        angle += 2.0 * math.pi
    while angle > math.pi:
        angle -= 2.0 * math.pi
    return angle


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
