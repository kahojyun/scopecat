"""Analysis APIs for post-run interpretation and online analysis."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
    from scopecat.api.analysis import (
        Analysis,
        AnalysisContext,
        AnalysisInput,
        AnalysisOutput,
        AnalysisStep,
        SavedAnalysis,
    )

_EXPORTS = {
    "Analysis": ("scopecat.api.analysis", "Analysis"),
    "AnalysisContext": ("scopecat.api.analysis", "AnalysisContext"),
    "AnalysisInput": ("scopecat.api.analysis", "AnalysisInput"),
    "AnalysisOutput": ("scopecat.api.analysis", "AnalysisOutput"),
    "AnalysisStep": ("scopecat.api.analysis", "AnalysisStep"),
    "EarlyStopDecision": ("scopecat.analysis.online", "EarlyStopDecision"),
    "SavedAnalysis": ("scopecat.api.analysis", "SavedAnalysis"),
    "decide_online_convergence": (
        "scopecat.analysis.online",
        "decide_online_convergence",
    ),
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisInput",
    "AnalysisOutput",
    "AnalysisStep",
    "EarlyStopDecision",
    "SavedAnalysis",
    "decide_online_convergence",
]
