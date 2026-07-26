"""Problem construction owned by the config-free authoring layer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)


def authoring_problem(
    code: str,
    message: str,
    root: str,
    *,
    path: Sequence[str | int] = (),
    phase: ProblemPhase = ProblemPhase.AUTHORING,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return problem(
        code=code,
        phase=phase,
        message=message,
        location=model_location(root, *path),
        details=details,
    )
