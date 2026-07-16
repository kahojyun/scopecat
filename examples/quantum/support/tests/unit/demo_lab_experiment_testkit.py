from __future__ import annotations

from dataclasses import replace

from scopecat.authoring import ExperimentInvocation
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.bound import BoundPlan
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.config.profiles import load_config_profile
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.config import ConfigProfileSnapshot

from .demo_lab_test_paths import EXPERIMENT_FIXTURE_DIR


def load_experiment_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")


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
