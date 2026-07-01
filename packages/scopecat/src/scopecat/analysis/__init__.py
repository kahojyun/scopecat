"""Analysis APIs for post-run interpretation and online analysis."""

from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
from scopecat.session_analysis import (
    Analysis,
    AnalysisContext,
    AnalysisExternalRef,
    AnalysisOutput,
    AnalysisStep,
    PromotedAnalysisStep,
    SavedAnalysis,
)

__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisExternalRef",
    "AnalysisOutput",
    "AnalysisStep",
    "EarlyStopDecision",
    "PromotedAnalysisStep",
    "SavedAnalysis",
    "decide_online_convergence",
]
