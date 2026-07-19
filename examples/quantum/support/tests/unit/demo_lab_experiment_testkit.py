from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import cast

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
from scopecat.compiler.typed.records import point_coordinate_ids
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.config.profiles import load_config_profile
from scopecat.execution.local.program import ComputeOperation, LocalOperation
from scopecat.execution.points import RunPoint
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements._bridge import (
    project_measurement_catalog,
    project_run_point_catalog,
)
from scopecat.measurements.projection import (
    MeasurementProjection,
    select_measurement_projection,
)
from scopecat.measurements.results import CoordinateValue
from scopecat.planning.authoring import resolve_experiment
from scopecat.planning.local_effects import (
    MaterializedLocalEffects as LocalEffects,
)
from scopecat.planning.local_effects import local_operation_resource_claims
from scopecat.planning.local_materialization import (
    materialize_local_execution,
    prepare_local_target,
)
from scopecat.records.config import ConfigProfileSnapshot

from .demo_lab_test_paths import EXPERIMENT_FIXTURE_DIR


@dataclass(frozen=True, slots=True)
class MaterializedPointEffects:
    point_index: int
    logical_id: LogicalPointId
    coordinates: Mapping[str, CoordinateValue]
    operations: tuple[LocalOperation, ...]


@dataclass(frozen=True, slots=True)
class MaterializedLocalEffects:
    points: tuple[MaterializedPointEffects, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]
    run_compute_operations: tuple[ComputeOperation, ...] = ()


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


def materialized_effects(
    invocation: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> MaterializedLocalEffects:
    """Compile an invocation for direct test-only inspection."""

    linked_points = _materialized_linked_points(invocation, config=config)
    target = prepare_local_target(
        linked_points.linked_plan,
        product_use_ids=frozenset(
            use.id for use in linked_points.linked_plan.program.product_uses
        ),
    )
    lowered: LocalEffects = materialize_local_execution(
        linked_points,
        target=target,
        point_count=len(linked_points.point_domain.points),
    )
    coordinate_ids = set(point_coordinate_ids(linked_points.point_domain.points))
    operations_by_point: dict[int, list[LocalOperation]] = {
        point.logical_ordinal: [] for point in linked_points.point_domain.points
    }
    ordered_effects = (
        *lowered.compute_operations,
        *(effect for group in lowered.effect_operations for effect in group),
        *lowered.collect_operations,
    )
    for effect in ordered_effects:
        for point_index in effect.point_indices:
            operations_by_point[point_index].append(effect.operation)
    claims = tuple(
        dict.fromkeys(
            claim
            for effect in ordered_effects
            for claim in local_operation_resource_claims(effect.operation)
        )
    )
    instrument_ids = {claim.id for claim in claims if claim.kind == "instrument"}
    resource_order = (
        *(item for item in target.instrument_order if item in instrument_ids),
        *sorted(instrument_ids - set(target.instrument_order)),
    )
    return MaterializedLocalEffects(
        points=tuple(
            MaterializedPointEffects(
                point_index=point.logical_ordinal,
                logical_id=point.logical_id,
                coordinates={
                    name: cast("CoordinateValue", value)
                    for name, value in point.row.items()
                    if name in coordinate_ids
                },
                operations=tuple(operations_by_point[point.logical_ordinal]),
            )
            for point in linked_points.point_domain.points
        ),
        resource_order=resource_order,
        resource_claims=claims,
        run_compute_operations=target.run_operations,
    )


def operations_of_type[T: LocalOperation](
    point: MaterializedPointEffects,
    operation_type: type[T],
) -> tuple[T, ...]:
    """Select concrete point operations for focused test assertions."""

    return tuple(
        operation
        for operation in point.operations
        if isinstance(operation, operation_type)
    )


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


def measurement_projection_and_points(
    invocation: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> tuple[MeasurementProjection, tuple[RunPoint, ...]]:
    linked_points = _materialized_linked_points(invocation, config=config)
    return (
        select_measurement_projection(
            project_measurement_catalog(linked_points),
            linked_points.linked_plan.record_uses,
        ),
        project_run_point_catalog(linked_points).points,
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
