"""Notebook-first public workflow facade."""

from scopecat.session import (
    Analysis,
    AnalysisContext,
    AnalysisInput,
    AnalysisOutput,
    AnalysisStep,
    CandidateConfig,
    ComparisonHandle,
    Data,
    EarlyStopDecision,
    Experiment,
    PromotedAnalysisStep,
    Quantity,
    RunHandle,
    SavedAnalysis,
    Workspace,
    decide_online_convergence,
    delete_param_rows,
    insert_param_rows,
    open,  # noqa: A004
    set_param,
    update_param_rows,
)
from scopecat.workflows import PreviewExperimentResult, ValidateExperimentResult

Run = RunHandle

__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisInput",
    "AnalysisOutput",
    "AnalysisStep",
    "CandidateConfig",
    "ComparisonHandle",
    "Data",
    "EarlyStopDecision",
    "Experiment",
    "PreviewExperimentResult",
    "PromotedAnalysisStep",
    "Quantity",
    "Run",
    "RunHandle",
    "SavedAnalysis",
    "ValidateExperimentResult",
    "Workspace",
    "decide_online_convergence",
    "delete_param_rows",
    "insert_param_rows",
    "open",
    "set_param",
    "update_param_rows",
]
