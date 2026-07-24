"""Stable structured-problem contracts for integration adapters."""

from scopecat.kernel.problems import (
    ExternalLocation,
    LocationPathItem,
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemLocation,
    ProblemPhase,
    RuntimeLocation,
    StorageLocation,
    blocking_problem,
    has_blocking_problems,
    model_location,
)

__all__ = [
    "ExternalLocation",
    "LocationPathItem",
    "ModelLocation",
    "Problem",
    "ProblemCategory",
    "ProblemImpact",
    "ProblemLocation",
    "ProblemPhase",
    "RuntimeLocation",
    "StorageLocation",
    "blocking_problem",
    "has_blocking_problems",
    "model_location",
]
