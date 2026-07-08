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
    id: str = "readout.frequency.analysis"

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        raw = context.data.measurements()
        input_ref = dataset_storage_ref(raw.dataset_entry)
        summary = analyze_readout_frequency_measurements(
            measurements=raw.dataset.records,
            input_ref=input_ref,
            config=context.config,
        )
        parameter_patch = _readout_frequency_patch(context, summary.center)

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
                parameter_patch,
                reason=summary.reason,
                confidence=1.0,
            )
        )


__all__ = [
    "ReadoutFrequencyAnalysisStep",
]


def _readout_frequency_patch(
    context: sc.AnalysisContext,
    value: sc.Quantity,
):
    if context.config.parameter_catalog.scalar(READOUT_PARAMETER_ID) is not None:
        return sc.set_param(READOUT_PARAMETER_ID, value)
    return sc.update_param_rows(
        "qubits",
        key={"qubit": _run_qubit(context)},
        values={READOUT_PARAMETER_ID: value},
    )


def _run_qubit(context: sc.AnalysisContext) -> str:
    for route in context.run.preview.routes:
        if route.port_id != "readout":
            continue
        for resolved in route.resolved:
            if resolved.entity_ids:
                return resolved.entity_ids[0]
    return "q0"
