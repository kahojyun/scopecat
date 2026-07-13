from __future__ import annotations

from dataclasses import replace

from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.program import TypedProgram
from scopecat._relations import ParameterRelationData
from scopecat._workflows.preview import build_experiment_preview
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.preview import ExperimentPreview
from scopecat.problems import Problem
from tests.support.authoring import load_config


def preview_contract(
    experiment: TypedProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> ExperimentPreview:
    preview, problems = preview_result(
        experiment,
        parameters,
        config=config,
    )
    assert problems == ()
    return preview


def preview_result(
    experiment: TypedProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> tuple[ExperimentPreview, tuple[Problem, ...]]:
    environment = replace(
        validate_config_environment(config or load_config()),
        parameters=parameters,
    )
    plan = bind_program(experiment, environment)
    return build_experiment_preview(plan), plan.problems
