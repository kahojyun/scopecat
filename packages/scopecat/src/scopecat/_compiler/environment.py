"""Validated, normalized configuration input for compiler passes."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat._parameter_resolution import resolve_config_parameters
from scopecat._relations import ParameterRelationData
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.planning.validation import validate_config_profile
from scopecat.problems import Problem, has_blocking_problems
from scopecat.routing import RoutingView


@dataclass(frozen=True, slots=True)
class ValidatedConfigEnvironment:
    """One normalized config environment shared by every compile pass.

    Parameter normalization is deliberately performed once.  Downstream
    authoring, point binding, routing, preview, and execution planning all
    receive this same environment instead of independently resolving the
    accepted snapshot.
    """

    config: ConfigProfileSnapshot
    parameters: ParameterRelationData
    routing: RoutingView | None
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
    valid = not has_blocking_problems(problems)
    return ValidatedConfigEnvironment(
        config=config,
        parameters=resolved.data,
        routing=RoutingView.from_config(config) if valid else None,
        problems=tuple(problems),
    )


__all__ = ["ValidatedConfigEnvironment", "validate_config_environment"]
