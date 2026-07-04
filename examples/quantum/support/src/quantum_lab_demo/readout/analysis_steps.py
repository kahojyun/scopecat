"""Reusable readout analysis steps for vNext notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc
from scopecat.runs import dataset_storage_ref

from quantum_lab_demo.readout.analysis_calculations import (
    READOUT_PARAMETER_ID,
    analyze_readout_frequency_measurements,
    analyze_readout_iq_quality_measurements,
)


@dataclass
class ReadoutFrequencyAnalysisStep:
    id: str = "readout.frequency.analysis"

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        raw = context.data.measurements()
        input_ref = dataset_storage_ref(raw.dataset_entry)
        summary = analyze_readout_frequency_measurements(
            measurements=raw.dataset.records,
            input_ref=input_ref,
            config=context.config,
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
                sc.set_param(READOUT_PARAMETER_ID, summary.center),
                reason=summary.reason,
                confidence=1.0,
            )
        )


@dataclass
class ReadoutIQQualityAnalysisStep:
    id: str = "readout.iq_quality.analysis"

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        raw = context.data.measurements()
        input_ref = dataset_storage_ref(raw.dataset_entry)
        summary = analyze_readout_iq_quality_measurements(
            run_id=context.run.id,
            measurements=raw.dataset.records,
            input_ref=input_ref,
        )
        return (
            context.result("readout IQ quality analysis")
            .input(
                raw.dataset_entry.id,
                title="raw measurements",
                expected_kind="measurement_dataset",
            )
            .table(
                [
                    {
                        "measurement_count": summary.measurement_count,
                        "visibility": summary.visibility.value,
                        "snr": summary.snr.value,
                        "threshold": summary.threshold.value,
                        "figure_ref": summary.figure_ref,
                    }
                ],
                title="IQ quality summary",
            )
            .figure(
                {
                    "kind": "scatter",
                    "x": "i",
                    "y": "q",
                    "source_dataset": raw.dataset_entry.id,
                },
                title="IQ quality",
            )
        )


__all__ = [
    "ReadoutFrequencyAnalysisStep",
    "ReadoutIQQualityAnalysisStep",
]
