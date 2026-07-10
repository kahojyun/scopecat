"""Reusable readout analysis steps for vNext notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc
from scopecat.runs import dataset_storage_ref

from quantum_lab_demo.experiments.readout_analysis_calculations import (
    READOUT_PARAMETER_ID,
    analyze_readout_frequency_measurements,
)


@dataclass
class ReadoutFrequencyAnalysisStep:
    qubit: str
    id: str = "readout.frequency.analysis"

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        raw = context.data.measurements()
        input_ref = dataset_storage_ref(raw.dataset_entry)
        summary = analyze_readout_frequency_measurements(
            measurements=raw.dataset.records,
            input_ref=input_ref,
            config=context.config,
            qubit=self.qubit,
        )
        parameter_update = _readout_frequency_update(
            summary.center,
            qubit=self.qubit,
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
                parameter_update,
                reason=summary.reason,
                confidence=1.0,
            )
        )


__all__ = [
    "ReadoutFrequencyAnalysisStep",
]


def _readout_frequency_update(
    value: sc.Quantity,
    *,
    qubit: str,
):
    return sc.update_parameter_rows(
        "qubits",
        key={"qubit": qubit},
        values={READOUT_PARAMETER_ID: value},
    )
