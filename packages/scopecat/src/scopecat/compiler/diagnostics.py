"""Problem helpers for pure transient compiler passes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemLocation,
    ProblemPhase,
    problem,
)


class CompilerProblemError(Exception):
    """One expected compiler finding that a collecting pass may accumulate."""

    def __init__(self, problem: Problem) -> None:
        if problem.phase not in {ProblemPhase.AUTHORING, ProblemPhase.PLANNING}:
            msg = "compiler problem must belong to authoring or planning"
            raise ValueError(msg)
        self.problem = problem
        super().__init__(problem.message)


def compiler_problem(
    code: str,
    message: str,
    location: ModelLocation,
    *,
    phase: ProblemPhase = ProblemPhase.PLANNING,
    related_locations: Sequence[ProblemLocation] = (),
    details: Mapping[str, object] | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=phase,
        location=location,
        related_locations=related_locations,
        details=details,
    )
