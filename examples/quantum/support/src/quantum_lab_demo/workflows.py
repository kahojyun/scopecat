"""Reusable readout workflows for the demo quantum lab package."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc
from scopecat.models.parameter import Quantity

from quantum_lab_demo.fixtures import (
    DEFAULT_READOUT_FREQUENCY_WORKSPACE,
    DEFAULT_READOUT_IQ_WORKSPACE,
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
    READOUT_IQ_FIXTURE_DIR,
    READOUT_IQ_VIRTUAL_LAB_PROFILE,
)
from quantum_lab_demo.lab import (
    PathInput,
    readout_frequency_lab,
    readout_iq_lab,
)
from quantum_lab_demo.readout import (
    ReadoutFrequencyAnalysisStep,
    ReadoutIQQualityAnalysisStep,
    frequency_calibration,
    iq_quality,
)


@dataclass(frozen=True)
class ReadoutFrequencyWorkflowResult:
    run: sc.RunHandle
    analysis: sc.Analysis
    candidate: sc.CandidateConfig
    processed_points: int
    figure_ref: str


@dataclass(frozen=True)
class ReadoutIQWorkflowResult:
    run: sc.RunHandle
    analysis: sc.Analysis
    processed_shots: int
    figure_ref: str


def run_readout_frequency_workflow(
    *,
    qubit: str = "q0",
    lab: sc.Workspace | None = None,
    workspace: PathInput = DEFAULT_READOUT_FREQUENCY_WORKSPACE,
    config_profile: PathInput = READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json",
    virtual_lab_profile: PathInput = READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
) -> ReadoutFrequencyWorkflowResult:
    active_lab = lab or readout_frequency_lab(
        workspace=workspace,
        config_profile=config_profile,
        virtual_lab_profile=virtual_lab_profile,
    )
    run = active_lab.run(frequency_calibration(qubit=qubit))
    analysis = run.analyze(ReadoutFrequencyAnalysisStep())
    analysis.save()
    summary = _analysis_table_row(analysis, "fit summary")
    return ReadoutFrequencyWorkflowResult(
        run=run,
        analysis=analysis,
        candidate=analysis.candidate_config(),
        processed_points=_int_field(summary, "measurement_count"),
        figure_ref=_str_field(summary, "figure_ref"),
    )


def run_readout_iq_workflow(
    *,
    qubit: str = "q0",
    lab: sc.Workspace | None = None,
    workspace: PathInput = DEFAULT_READOUT_IQ_WORKSPACE,
    config_profile: PathInput = READOUT_IQ_FIXTURE_DIR / "config-profile.json",
    virtual_lab_profile: PathInput = READOUT_IQ_VIRTUAL_LAB_PROFILE,
) -> ReadoutIQWorkflowResult:
    active_lab = lab or readout_iq_lab(
        workspace=workspace,
        config_profile=config_profile,
        virtual_lab_profile=virtual_lab_profile,
    )
    run = active_lab.run(iq_quality(qubit=qubit))
    analysis = run.analyze(ReadoutIQQualityAnalysisStep())
    analysis.save()
    summary = _analysis_table_row(analysis, "IQ quality summary")
    return ReadoutIQWorkflowResult(
        run=run,
        analysis=analysis,
        processed_shots=_int_field(summary, "measurement_count"),
        figure_ref=_str_field(summary, "figure_ref"),
    )


def format_readout_frequency_summary(result: ReadoutFrequencyWorkflowResult) -> str:
    patch = result.candidate.parameter_changes[0].patches[0]
    value = patch.value
    if not isinstance(value, Quantity):
        msg = "readout frequency candidate is not a scalar quantity change"
        raise TypeError(msg)
    lines = [
        f"Run: {result.run.id}",
        f"Processed points: {result.processed_points}",
        f"Plot: {result.figure_ref}",
        (f"Candidate readout_frequency: {value.value} {value.unit}"),
    ]
    return "\n".join(lines)


def format_readout_iq_summary(result: ReadoutIQWorkflowResult) -> str:
    lines = [
        f"Run: {result.run.id}",
        f"Processed shots: {result.processed_shots}",
        f"Figure: {result.figure_ref}",
    ]
    return "\n".join(lines)


def _analysis_table_row(analysis: sc.Analysis, title: str) -> dict[str, object]:
    for output in analysis.outputs:
        if output.kind == "table" and output.title == title:
            rows = output.content
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                return rows[0]
    msg = f"analysis table not found: {title}"
    raise LookupError(msg)


def _int_field(row: dict[str, object], field: str) -> int:
    value = row[field]
    if not isinstance(value, int):
        msg = f"analysis field is not an integer: {field}"
        raise TypeError(msg)
    return value


def _str_field(row: dict[str, object], field: str) -> str:
    value = row[field]
    if not isinstance(value, str):
        msg = f"analysis field is not a string: {field}"
        raise TypeError(msg)
    return value


__all__ = [
    "ReadoutFrequencyWorkflowResult",
    "ReadoutIQWorkflowResult",
    "format_readout_frequency_summary",
    "format_readout_iq_summary",
    "run_readout_frequency_workflow",
    "run_readout_iq_workflow",
]
