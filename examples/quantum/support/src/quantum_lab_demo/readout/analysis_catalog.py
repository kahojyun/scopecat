"""Reusable readout analysis catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.workflows import (
    AnalysisCatalogDescription,
    AnalysisStepCatalogContext,
    AnalysisStepCatalogResult,
    AnalysisStepDescription,
)

from quantum_lab_demo.readout.analysis_steps import (
    ReadoutFrequencyAnalysisStep,
    ReadoutIQQualityAnalysisStep,
)

READOUT_FREQUENCY_ANALYSIS_STEP = "readout.frequency.analysis"
READOUT_IQ_QUALITY_ANALYSIS_STEP = "readout.iq_quality.analysis"


@dataclass(frozen=True)
class ReadoutAnalysisCatalog:
    catalog_id: str = "quantum_lab_demo.readout_analysis"
    metadata: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> AnalysisCatalogDescription:
        metadata = _catalog_metadata(self.catalog_id, self.metadata)
        return AnalysisCatalogDescription(
            catalog_id=self.catalog_id,
            steps=(
                AnalysisStepDescription(
                    step_id=READOUT_FREQUENCY_ANALYSIS_STEP,
                    label="Readout frequency analysis",
                    description=(
                        "Analyze a readout frequency scan, record notebook-style "
                        "outputs, and emit a readout_frequency proposal."
                    ),
                    input_artifact_kinds=("measurement_dataset",),
                    output_artifact_kinds=("analysis",),
                    proposal_kinds=("readout_frequency",),
                    metadata=metadata,
                ),
                AnalysisStepDescription(
                    step_id=READOUT_IQ_QUALITY_ANALYSIS_STEP,
                    label="Readout IQ quality analysis",
                    description=(
                        "Analyze shot-level readout IQ records into notebook-style "
                        "quality metrics and figure hints."
                    ),
                    input_artifact_kinds=("measurement_dataset",),
                    output_artifact_kinds=("analysis",),
                    metadata=metadata,
                ),
            ),
            metadata=metadata,
        )

    def analysis_step(
        self, context: AnalysisStepCatalogContext
    ) -> AnalysisStepCatalogResult:
        metadata = _catalog_metadata(self.catalog_id, self.metadata)
        if context.step_id == READOUT_FREQUENCY_ANALYSIS_STEP:
            return AnalysisStepCatalogResult(
                step=ReadoutFrequencyAnalysisStep(),
                metadata=metadata,
            )
        if context.step_id == READOUT_IQ_QUALITY_ANALYSIS_STEP:
            return AnalysisStepCatalogResult(
                step=ReadoutIQQualityAnalysisStep(),
                metadata=metadata,
            )
        return AnalysisStepCatalogResult(
            diagnostics=(
                _diagnostic(
                    "error",
                    "readout_analysis_step_unsupported",
                    f"unsupported readout analysis step {context.step_id}",
                    "step_id",
                ),
            ),
            metadata=metadata,
        )


def _catalog_metadata(catalog_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {"catalog_id": catalog_id, **metadata}


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "READOUT_FREQUENCY_ANALYSIS_STEP",
    "READOUT_IQ_QUALITY_ANALYSIS_STEP",
    "ReadoutAnalysisCatalog",
]
