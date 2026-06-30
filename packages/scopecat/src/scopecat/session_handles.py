"""Notebook facade handle exports."""

from __future__ import annotations

from scopecat.session_analysis import (
    Analysis,
    AnalysisContext,
    AnalysisExternalRef,
    AnalysisOutput,
    AnalysisStep,
    PromotedAnalysisStep,
    SavedAnalysis,
)
from scopecat.session_candidate_config import (
    CandidateConfig,
    CandidateConfigReview,
    ParameterGuess,
)
from scopecat.session_comparison import ComparisonHandle
from scopecat.session_data import Data
from scopecat.session_overview import OverviewHandle
from scopecat.session_run_handle import RunHandle, run_handle_id
from scopecat.session_templates import TemplateBrowser

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
    "OverviewHandle",
    "ParameterGuess",
    "PromotedAnalysisStep",
    "RunHandle",
    "SavedAnalysis",
    "TemplateBrowser",
    "run_handle_id",
]
