"""Validated, normalized configuration input for compiler passes."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.kernel.problems import Problem, has_blocking_problems
from scopecat.planning.validation import validate_config_profile
from scopecat.records.config import ConfigProfileSnapshot


@dataclass(frozen=True, slots=True)
class ValidatedConfigEnvironment:
    """One normalized config environment shared by every compile pass.

    Parameter normalization is deliberately performed once. Downstream passes
    receive the same accepted config and parameter data without carrying
    target-specific planning state.
    """

    config: ConfigProfileSnapshot
    parameters: ParameterRelationData
    problems: tuple[Problem, ...]

    @property
    def valid(self) -> bool:
        return not has_blocking_problems(self.problems)


def validate_config_environment(
    config: ConfigProfileSnapshot,
) -> ValidatedConfigEnvironment:
    resolved = resolve_config_parameters(config)
    problems = (
        *validate_config_profile(config, include_parameter_values=False),
        *resolved.problems,
    )
    return ValidatedConfigEnvironment(
        config=config,
        parameters=resolved.data,
        problems=tuple(problems),
    )
