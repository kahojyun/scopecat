from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from scopecat.authoring import ExperimentInvocation
from scopecat.compiler.frontend.environment import (
    ValidatedConfigEnvironment,
    validate_config_environment,
)
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    link_verified_program,
    materialize_linked_points,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.problems import ProblemPhase
from scopecat.measurements._bridge import project_measurement_catalog
from scopecat.measurements.projection import (
    MeasurementProjection,
    select_measurement_projection,
)
from scopecat.planning.authoring import resolve_experiment
from scopecat.planning.local_materialization import (
    MaterializedLocalEffects,
    materialize_local_execution,
)
from scopecat.records.config import ConfigProfileSnapshot

from .demo_lab_test_paths import EXPERIMENT_FIXTURE_DIR


def load_experiment_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")


def link_program(
    program: CoreProgram,
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
) -> MaterializedLocalEffects:
    """Compile an invocation for direct test-only inspection."""

    linked_points = _materialized_linked_points(invocation, config=config)
    plan = materialize_local_execution(linked_points)
    return plan


def measurement_projection(
    invocation: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> MeasurementProjection:
    """Build the production record projection for focused shape assertions."""

    linked_points = _materialized_linked_points(invocation, config=config)
    return select_measurement_projection(
        project_measurement_catalog(linked_points),
        linked_points.linked_plan.record_uses,
    )


def _materialized_linked_points(
    invocation: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot | None,
) -> MaterializedLinkedPoints:
    selected_config = config or load_experiment_config()
    resolved = resolve_experiment(invocation, config_profile=selected_config)
    environment = replace(
        validate_config_environment(selected_config),
        parameters=resolved.parameters,
    )
    return materialize_linked_points(link_program(resolved.experiment, environment))
