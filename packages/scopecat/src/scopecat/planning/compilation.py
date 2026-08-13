"""Compile bound experiment semantics into an executable run program."""

from __future__ import annotations

from scopecat.compiler.bind import BoundPlan
from scopecat.execution.program import RunProgram
from scopecat.kernel.errors import CheckFailed, ProblemFailure
from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.optimization import AdaptivePointPlan
from scopecat.planning.system import ExperimentSystem


def compile_run_program(
    system: ExperimentSystem | None,
    *,
    bound: BoundPlan,
    adaptive_point_plan: AdaptivePointPlan | None = None,
) -> RunProgram:
    """Compile with the selected experiment system."""

    if system is None:
        raise CheckFailed(
            (
                problem(
                    "execution.experiment_system_missing",
                    "experiment planning requires an explicit experiment system",
                    phase=ProblemPhase.PLANNING,
                    location=model_location("run_options", "experiment_system"),
                ),
            )
        )

    try:
        return system.compile(bound, adaptive_point_plan=adaptive_point_plan)
    except ProblemFailure as error:
        raise CheckFailed(
            tuple(
                item.model_copy(update={"phase": ProblemPhase.PLANNING})
                for item in error.problems
            )
        ) from error


__all__ = ["compile_run_program"]
