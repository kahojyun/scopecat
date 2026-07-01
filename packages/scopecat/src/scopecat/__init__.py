"""Notebook-first public workflow facade."""

from scopecat.session import (
    Analysis,
    AnalysisContext,
    AnalysisExternalRef,
    AnalysisOutput,
    AnalysisStep,
    CandidateConfig,
    CandidateConfigReview,
    ComparisonHandle,
    Data,
    EarlyStopDecision,
    Experiment,
    OverviewHandle,
    ParameterGuess,
    PromotedAnalysisStep,
    RunHandle,
    SavedAnalysis,
    Workspace,
    decide_online_convergence,
    open,  # noqa: A004
)

Run = RunHandle

__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisExternalRef",
    "AnalysisOutput",
    "AnalysisStep",
    "CandidateConfig",
    "CandidateConfigReview",
    "ComparisonHandle",
    "Data",
    "EarlyStopDecision",
    "Experiment",
    "OverviewHandle",
    "ParameterGuess",
    "PromotedAnalysisStep",
    "Run",
    "RunHandle",
    "SavedAnalysis",
    "Workspace",
    "decide_online_convergence",
    "open",
]
