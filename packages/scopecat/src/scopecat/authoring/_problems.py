"""Problem construction owned by the config-free authoring layer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)


def authoring_problem(
    code: str,
    message: str,
    root: str,
    *,
    path: Sequence[str | int] = (),
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code=code,
        category=category,
        phase=phase,
        message=message,
        location=model_location(root, *path),
        details=details,
    )


__all__ = ["authoring_problem"]
