"""Structured, side-effect-free experiment check results."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.problems import Problem, has_blocking_problems
from scopecat.planning.preview_models import ExperimentPreview


@dataclass(frozen=True, slots=True)
class ExperimentCheckResult:
    """Structured outcome of an experiment check."""

    problems: tuple[Problem, ...]
    preview: ExperimentPreview | None

    def __post_init__(self) -> None:
        problems = tuple(self.problems)
        has_blockers = has_blocking_problems(problems)
        if (self.preview is not None) == has_blockers:
            msg = (
                "a successful experiment check requires a preview and a failed "
                "check requires blocking problems"
            )
            raise ValueError(msg)
        object.__setattr__(self, "problems", problems)

    @property
    def ok(self) -> bool:
        return self.preview is not None
