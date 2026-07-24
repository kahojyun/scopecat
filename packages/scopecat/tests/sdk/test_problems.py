from __future__ import annotations

import scopecat.kernel.problems as kernel_problems
import scopecat.sdk.problems as problems


def test_sdk_problem_contracts_are_the_canonical_problem_types() -> None:
    assert problems.ExternalLocation is kernel_problems.ExternalLocation
    assert problems.LocationPathItem is kernel_problems.LocationPathItem
    assert problems.ModelLocation is kernel_problems.ModelLocation
    assert problems.Problem is kernel_problems.Problem
    assert problems.ProblemCategory is kernel_problems.ProblemCategory
    assert problems.ProblemImpact is kernel_problems.ProblemImpact
    assert problems.ProblemLocation is kernel_problems.ProblemLocation
    assert problems.ProblemPhase is kernel_problems.ProblemPhase
    assert problems.RuntimeLocation is kernel_problems.RuntimeLocation
    assert problems.StorageLocation is kernel_problems.StorageLocation
    assert problems.blocking_problem is kernel_problems.blocking_problem
    assert problems.has_blocking_problems is kernel_problems.has_blocking_problems
    assert problems.model_location is kernel_problems.model_location


def test_sdk_problem_surface_is_explicit() -> None:
    assert set(problems.__all__) == {
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
    }
