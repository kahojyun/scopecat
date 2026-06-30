"""Plot-report processing for readout-frequency calibration scans."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import ProcessingJob
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
from quantum_lab_demo.readout.frequency_processing import (
    MEASUREMENT_DATASET_ARTIFACT_KIND,
    PROCESSED_DATA_ARTIFACT_ID,
)
from quantum_lab_demo.readout.responses import _frequency_to_ghz

READOUT_PLOT_REPORT_STEP = "readout-frr-plot-report"
READOUT_PLOT_REPORT_RESULT_REF = "artifacts/readout-frr-plot-report.json"
READOUT_PLOT_REPORT_SUMMARY_REF = "artifacts/readout-frr-plot-report.md"
READOUT_PLOT_REPORT_FIGURE_REF = "artifacts/readout-frr-plot-report.png"
READOUT_PLOT_REPORT_JOB_REF = "processing/readout-frr-plot-report.job.json"
READOUT_PLOT_REPORT_RESULT_ARTIFACT_ID = "readout-frr-plot-report-result"
READOUT_PLOT_REPORT_SUMMARY_ARTIFACT_ID = "readout-frr-plot-report-summary"
READOUT_PLOT_REPORT_FIGURE_ARTIFACT_ID = "readout-frr-plot-report-figure"
READOUT_PLOT_REPORT_JOB_ARTIFACT_ID = "readout-frr-plot-report-job"

_EXPECTED_OBSERVABLE_UNITS = {
    "s21_db": "dB",
    "iq_amplitude": "ratio",
    "iq_phase": "rad",
    "readout_detuning": "MHz",
    "i": "ratio",
    "q": "ratio",
}


@dataclass(frozen=True)
class _ReadoutPlotPoint:
    point_index: int
    frequency_ghz: float
    s21_db: float
    iq_amplitude: float
    iq_phase: float
    readout_detuning_mhz: float
    i_value: float
    q_value: float
    frequency_quantity: Quantity


class ReadoutFrequencyPlotReportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "quantum_lab_demo.readout_frequency_plot_report_result.v0"
    run_id: str
    step: str = READOUT_PLOT_REPORT_STEP
    input_ref: str
    figure_ref: str
    measurement_count: int
    min_s21_point_index: int
    min_s21: Quantity
    min_s21_readout_frequency: Quantity
    max_amplitude: Quantity
    min_amplitude: Quantity
    frequency_span: Quantity
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def execute_readout_frequency_plot_report(
    *, run_id: str, workspace: str | Path
) -> tuple[ProcessingJob, ReadoutFrequencyPlotReportResult]:
    return execute_processing_step(
        run_id=run_id,
        workspace=workspace,
        step=ReadoutFrequencyPlotReportStep(),
    )


@dataclass(frozen=True)
class ReadoutFrequencyPlotReportStep:
    step_id: str = READOUT_PLOT_REPORT_STEP

    def run(
        self, context: ProcessingContext
    ) -> ProcessingStepResult[ReadoutFrequencyPlotReportResult]:
        input_artifact = context.inputs.resolve_artifact(
            selector=PROCESSED_DATA_ARTIFACT_ID,
            expected_kind=MEASUREMENT_DATASET_ARTIFACT_KIND,
            diagnostics=ArtifactInputDiagnostics(
                not_found_code="readout_plot_report_input_not_found",
                invalid_kind_code="readout_plot_report_input_kind_unsupported",
                path_escape_code="readout_plot_report_input_path_escape",
                not_found_message="readout plot report input artifact not found",
                invalid_kind_message=(
                    "readout plot report supports measurement_dataset only"
                ),
                path_escape_message=(
                    "readout plot report input selector escapes run directory"
                ),
                diagnostic_path="input",
            ),
        )
        dataset = context.inputs.read_measurement_dataset(
            input_artifact,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="missing_readout_plot_report_input",
                empty_code="empty_readout_plot_report_input",
                invalid_code="invalid_readout_plot_report_input",
                missing_schema_code="missing_readout_plot_report_input_schema",
                invalid_schema_code="invalid_readout_plot_report_input_schema",
                noun="readout plot report input",
                diagnostic_path=input_artifact.ref,
            ),
        )
        measurements = dataset.records
        points = _plot_points(measurements=measurements, input_ref=input_artifact.ref)
        best_point = min(points, key=lambda point: (point.s21_db, point.point_index))
        min_amplitude = min(points, key=lambda point: point.iq_amplitude).iq_amplitude
        max_amplitude = max(points, key=lambda point: point.iq_amplitude).iq_amplitude
        min_frequency = min(point.frequency_ghz for point in points)
        max_frequency = max(point.frequency_ghz for point in points)

        result = ReadoutFrequencyPlotReportResult(
            run_id=context.run_id,
            input_ref=input_artifact.ref,
            figure_ref=READOUT_PLOT_REPORT_FIGURE_REF,
            measurement_count=len(points),
            min_s21_point_index=best_point.point_index,
            min_s21=Quantity(value=best_point.s21_db, unit="dB"),
            min_s21_readout_frequency=best_point.frequency_quantity,
            max_amplitude=Quantity(value=max_amplitude, unit="ratio"),
            min_amplitude=Quantity(value=min_amplitude, unit="ratio"),
            frequency_span=Quantity(
                value=round(max_frequency - min_frequency, 12),
                unit="GHz",
            ),
        )
        context.artifacts.write_model(
            id=READOUT_PLOT_REPORT_RESULT_ARTIFACT_ID,
            kind="readout_plot_report_result",
            filename=_artifact_filename(READOUT_PLOT_REPORT_RESULT_REF),
            model=result,
            media_type="application/json",
        )
        context.artifacts.write_text(
            id=READOUT_PLOT_REPORT_SUMMARY_ARTIFACT_ID,
            kind="summary",
            filename=_artifact_filename(READOUT_PLOT_REPORT_SUMMARY_REF),
            content=render_readout_frequency_plot_report_summary(result),
            media_type="text/markdown",
        )
        context.artifacts.write_bytes(
            id=READOUT_PLOT_REPORT_FIGURE_ARTIFACT_ID,
            kind="plot",
            filename=_artifact_filename(READOUT_PLOT_REPORT_FIGURE_REF),
            content=_render_plot_report_figure(
                points=points,
                best_point=best_point,
            ),
            media_type="image/png",
            metadata={"source_step": READOUT_PLOT_REPORT_STEP},
        )
        return ProcessingStepResult(
            result=result,
            job_id=READOUT_PLOT_REPORT_STEP,
            job_ref=READOUT_PLOT_REPORT_JOB_REF,
            job_artifact=ProcessingJobArtifact(
                id=READOUT_PLOT_REPORT_JOB_ARTIFACT_ID,
            ),
        )


def render_readout_frequency_plot_report_summary(
    result: ReadoutFrequencyPlotReportResult,
) -> str:
    lines = [
        "# Readout FRR Plot Report",
        "",
        f"- Run ID: {result.run_id}",
        f"- Step: {result.step}",
        f"- Input: {result.input_ref}",
        f"- Figure: {result.figure_ref}",
        f"- Measurements: {result.measurement_count}",
        f"- Minimum S21 point: {result.min_s21_point_index}",
        f"- Minimum S21: {result.min_s21.value} {result.min_s21.unit}",
        (
            f"- Minimum S21 readout frequency: "
            f"{result.min_s21_readout_frequency.value} "
            f"{result.min_s21_readout_frequency.unit}"
        ),
        f"- Amplitude range: {result.min_amplitude.value} to "
        f"{result.max_amplitude.value} {result.max_amplitude.unit}",
        f"- Frequency span: {result.frequency_span.value} {result.frequency_span.unit}",
        "",
    ]
    return "\n".join(lines) + "\n"


def _plot_points(
    *, measurements: list[MeasurementRecord], input_ref: str
) -> list[_ReadoutPlotPoint]:
    return [
        _plot_point(measurement=measurement, input_ref=input_ref)
        for measurement in measurements
    ]


def _plot_point(*, measurement: MeasurementRecord, input_ref: str) -> _ReadoutPlotPoint:
    frequency = measurement.coordinates.get("readout_frequency")
    if frequency is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_plot_parameter",
                    "readout plot report measurement is missing readout_frequency",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    return _ReadoutPlotPoint(
        point_index=measurement.point_index,
        frequency_ghz=_frequency_to_ghz(frequency),
        s21_db=_observable_value(
            measurement=measurement,
            observable_id="s21_db",
            input_ref=input_ref,
        ),
        iq_amplitude=_observable_value(
            measurement=measurement,
            observable_id="iq_amplitude",
            input_ref=input_ref,
        ),
        iq_phase=_observable_value(
            measurement=measurement,
            observable_id="iq_phase",
            input_ref=input_ref,
        ),
        readout_detuning_mhz=_observable_value(
            measurement=measurement,
            observable_id="readout_detuning",
            input_ref=input_ref,
        ),
        i_value=_observable_value(
            measurement=measurement,
            observable_id="i",
            input_ref=input_ref,
        ),
        q_value=_observable_value(
            measurement=measurement,
            observable_id="q",
            input_ref=input_ref,
        ),
        frequency_quantity=frequency,
    )


def _observable_value(
    *,
    measurement: MeasurementRecord,
    observable_id: str,
    input_ref: str,
) -> float:
    expected_unit = _EXPECTED_OBSERVABLE_UNITS[observable_id]
    observable = measurement.observables.get(observable_id)
    if observable is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_readout_plot_observable",
                    f"readout plot report measurement is missing {observable_id}",
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    if observable.unit != expected_unit:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_readout_plot_observable",
                    (
                        f"readout plot report observable {observable_id} "
                        f"must use {expected_unit} unit"
                    ),
                    _measurement_path(input_ref, measurement),
                )
            ]
        )
    return observable.value


def _render_plot_report_figure(
    *,
    points: list[_ReadoutPlotPoint],
    best_point: _ReadoutPlotPoint,
) -> bytes:
    frequencies = [point.frequency_ghz for point in points]
    s21_values = [point.s21_db for point in points]
    amplitudes = [point.iq_amplitude for point in points]
    phases = [point.iq_phase for point in points]
    i_values = [point.i_value for point in points]
    q_values = [point.q_value for point in points]

    figure, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    ((s21_axis, amplitude_axis), (phase_axis, iq_axis)) = axes

    s21_axis.plot(frequencies, s21_values, color="#1f77b4", linewidth=1.5)
    s21_axis.scatter(
        [best_point.frequency_ghz],
        [best_point.s21_db],
        color="#d62728",
        s=42,
        zorder=3,
    )
    s21_axis.set_title("S21")
    s21_axis.set_xlabel("Readout frequency (GHz)")
    s21_axis.set_ylabel("S21 (dB)")

    amplitude_axis.plot(frequencies, amplitudes, color="#2ca02c", linewidth=1.5)
    amplitude_axis.scatter(
        [best_point.frequency_ghz],
        [best_point.iq_amplitude],
        color="#d62728",
        s=42,
        zorder=3,
    )
    amplitude_axis.set_title("IQ amplitude")
    amplitude_axis.set_xlabel("Readout frequency (GHz)")
    amplitude_axis.set_ylabel("Amplitude (ratio)")

    phase_axis.plot(frequencies, phases, color="#9467bd", linewidth=1.5)
    phase_axis.scatter(
        [best_point.frequency_ghz],
        [best_point.iq_phase],
        color="#d62728",
        s=42,
        zorder=3,
    )
    phase_axis.set_title("IQ phase")
    phase_axis.set_xlabel("Readout frequency (GHz)")
    phase_axis.set_ylabel("Phase (rad)")

    iq_axis.plot(i_values, q_values, color="#ff7f0e", linewidth=1.2)
    iq_axis.scatter(i_values, q_values, color="#ff7f0e", s=14)
    iq_axis.scatter(
        [best_point.i_value],
        [best_point.q_value],
        color="#d62728",
        s=42,
        zorder=3,
    )
    iq_axis.set_title("IQ trace")
    iq_axis.set_xlabel("I (ratio)")
    iq_axis.set_ylabel("Q (ratio)")
    iq_axis.set_aspect("equal", adjustable="datalim")

    for axis in (s21_axis, amplitude_axis, phase_axis, iq_axis):
        axis.grid(True, alpha=0.25)

    output = BytesIO()
    figure.savefig(output, format="png", dpi=160)
    plt.close(figure)
    return output.getvalue()


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
