"""Normalized configuration input for compiler passes."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.kernel.errors import CheckFailed
from scopecat.planning.validation import validate_config_profile
from scopecat.records.config import ConfigProfileSnapshot


@dataclass(frozen=True, slots=True)
class ConfigEnvironment:
    """One accepted config environment shared by every compile pass.

    Parameter normalization is deliberately performed once. Downstream passes
    only receive the successful state, so they do not repeat config checks.
    """

    config: ConfigProfileSnapshot
    parameters: ParameterRelationData


def build_config_environment(
    config: ConfigProfileSnapshot,
) -> ConfigEnvironment:
    resolved = resolve_config_parameters(config)
    problems = (
        *validate_config_profile(config, include_parameter_values=False),
        *resolved.problems,
    )
    if problems:
        raise CheckFailed(problems)
    return ConfigEnvironment(
        config=config,
        parameters=resolved.data,
    )
