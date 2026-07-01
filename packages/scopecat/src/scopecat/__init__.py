"""Notebook-first public workflow facade."""

from scopecat.session import (
    Analysis,
    AnalysisArtifactRef,
    AnalysisContext,
    AnalysisInputRef,
    AnalysisOutput,
    AnalysisStep,
    CandidateConfig,
    CandidateConfigReview,
    ComparisonHandle,
    Data,
    EarlyStopDecision,
    Experiment,
    OverviewHandle,
    ParameterProposal,
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
    "AnalysisArtifactRef",
    "AnalysisContext",
    "AnalysisInputRef",
    "AnalysisOutput",
    "AnalysisStep",
    "CandidateConfig",
    "CandidateConfigReview",
    "ComparisonHandle",
    "Data",
    "EarlyStopDecision",
    "Experiment",
    "OverviewHandle",
    "ParameterProposal",
    "PromotedAnalysisStep",
    "Run",
    "RunHandle",
    "SavedAnalysis",
    "Workspace",
    "decide_online_convergence",
    "open",
]
