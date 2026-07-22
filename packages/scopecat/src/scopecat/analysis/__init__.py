"""Analysis APIs for post-run interpretation and online analysis."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
    from scopecat.api.analysis import (
        Analysis,
        AnalysisContext,
        AnalysisDefinition,
        AnalysisInput,
        AnalysisInvocation,
        AnalysisOutput,
        AnalysisStep,
        SavedAnalysis,
        analysis_step,
    )

_EXPORTS = {
    "Analysis": ("scopecat.api.analysis", "Analysis"),
    "AnalysisContext": ("scopecat.api.analysis", "AnalysisContext"),
    "AnalysisDefinition": ("scopecat.api.analysis", "AnalysisDefinition"),
    "AnalysisInput": ("scopecat.api.analysis", "AnalysisInput"),
    "AnalysisInvocation": ("scopecat.api.analysis", "AnalysisInvocation"),
    "AnalysisOutput": ("scopecat.api.analysis", "AnalysisOutput"),
    "AnalysisStep": ("scopecat.api.analysis", "AnalysisStep"),
    "EarlyStopDecision": ("scopecat.analysis.online", "EarlyStopDecision"),
    "SavedAnalysis": ("scopecat.api.analysis", "SavedAnalysis"),
    "analysis_step": ("scopecat.api.analysis", "analysis_step"),
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
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisDefinition",
    "AnalysisInput",
    "AnalysisInvocation",
    "AnalysisOutput",
    "AnalysisStep",
    "EarlyStopDecision",
    "SavedAnalysis",
    "analysis_step",
    "decide_online_convergence",
]
