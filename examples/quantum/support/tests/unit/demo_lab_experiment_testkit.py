from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from scopecat.authoring import ExperimentInvocation
from scopecat.compiler.frontend.environment import (
    ValidatedConfigEnvironment,
    validate_config_environment,
)
from scopecat.compiler.linking.bound import BoundPlan
from scopecat.compiler.linking.linked import LinkedPlan, link_verified_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.typed.program import TypedProgram
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.problems import ProblemPhase
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.config import ConfigProfileSnapshot

from .demo_lab_test_paths import EXPERIMENT_FIXTURE_DIR


def load_experiment_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")


def link_program(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
) -> LinkedPlan:
    """Snapshot, seal, and link an externally constructed test program."""

    return link_verified_program(
        seal_typed_program(deepcopy(program), phase=ProblemPhase.PLANNING),
        environment,
    )


def bound_plan(
    invocation: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> BoundPlan:
    """Compile an invocation for direct test-only inspection."""

    selected_config = config or load_experiment_config()
    resolved = resolve_experiment(invocation, config_profile=selected_config)
    environment = replace(
        validate_config_environment(selected_config),
        parameters=resolved.parameters,
    )
    plan = materialize_local_plan(link_program(resolved.experiment, environment))
    assert plan.problems == ()
    return plan
