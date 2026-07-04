"""Analysis APIs for post-run interpretation and online analysis."""

from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
from scopecat.session_analysis import (
    Analysis,
    AnalysisContext,
    AnalysisInput,
    AnalysisOutput,
    AnalysisStep,
    PromotedAnalysisStep,
    SavedAnalysis,
)

__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisInput",
    "AnalysisOutput",
    "AnalysisStep",
    "EarlyStopDecision",
    "PromotedAnalysisStep",
    "SavedAnalysis",
    "decide_online_convergence",
]
