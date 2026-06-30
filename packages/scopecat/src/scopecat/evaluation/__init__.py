"""Evaluation pipelines for Scopecat runs."""

from scopecat.evaluation.online import EarlyStopDecision, decide_online_convergence
from scopecat.evaluation.sdk import (
    ArtifactInputDiagnostics,
    EvaluationArtifactHandle,
    EvaluationArtifactWriter,
    EvaluationContext,
    EvaluationInputArtifact,
    EvaluationInputResolver,
    EvaluationJob,
    EvaluationJobArtifact,
    EvaluationProposalHandle,
    EvaluationProposalStore,
    EvaluationStep,
    EvaluationStepResult,
    MeasurementInputDiagnostics,
    execute_evaluation_step,
)

__all__ = [
    "ArtifactInputDiagnostics",
    "EarlyStopDecision",
    "EvaluationArtifactHandle",
    "EvaluationArtifactWriter",
    "EvaluationContext",
    "EvaluationInputArtifact",
    "EvaluationInputResolver",
    "EvaluationJob",
    "EvaluationJobArtifact",
    "EvaluationProposalHandle",
    "EvaluationProposalStore",
    "EvaluationStep",
    "EvaluationStepResult",
    "MeasurementInputDiagnostics",
    "decide_online_convergence",
    "execute_evaluation_step",
]
