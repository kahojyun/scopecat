from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from scopecat.api.workspace import Workspace
from scopecat.authoring import ExperimentInvocation
from scopecat.compiler.frontend.environment import (
    ValidatedConfigEnvironment,
    validate_config_environment,
)
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    LinkedPointMaterializer,
    MaterializedLinkedPoints,
    link_verified_program,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.composition.embedded import open_embedded_workspace
from scopecat.config.profiles import load_config_profile
from scopecat.execution.local.program import ComputeOperation, LocalOperation
from scopecat.execution.points import RunPoint
from scopecat.execution.program import RunCoverageEffect
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

from quantum_lab_demo.compiler import QuantumLabCompiler, QuantumRealtimeLabCompiler
from quantum_lab_demo.lab import quantum_lab_config_profile, quantum_lab_system

from .demo_lab_test_paths import EXPERIMENT_FIXTURE_DIR
from .demo_lab_test_paths import (
    EXPERIMENT_VIRTUAL_LAB_PROFILE as TEST_VIRTUAL_LAB_PROFILE,
)

PathInput = str | Path


def embedded_quantum_lab(
    *,
    workspace: PathInput,
    config_profile: PathInput | ConfigProfileSnapshot | None = None,
    virtual_lab_profile: PathInput = TEST_VIRTUAL_LAB_PROFILE,
    compiler: QuantumLabCompiler | QuantumRealtimeLabCompiler | None = None,
) -> Workspace:
    """Compose isolated storage for unit tests that do not exercise the daemon."""

    config = quantum_lab_config_profile(config_profile)
    return open_embedded_workspace(
        workspace,
        config_profile=config,
        system=quantum_lab_system(
            config=config,
            virtual_lab_profile=virtual_lab_profile,
            compiler=compiler,
        ),
    )


@dataclass(frozen=True, slots=True)
class LocalEffectInspection:
    """Production-aligned view of logical points and local effect coverage."""

    points: tuple[RunPoint, ...]
    effects: tuple[RunCoverageEffect, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]
    preamble_operations: tuple[ComputeOperation, ...] = ()


_BIND_DOMAIN_INPUTS = LinkedPointMaterializer.bind_domain_inputs


def reject_program_input_binding(
    materializer: LinkedPointMaterializer,
    execution_id: str,
    input_kind: Literal["program", "compiler"],
    input_ids: Sequence[str],
    ordinals: Sequence[int],
    *,
    max_points: int,
    coverage: MaterializedLinkedPoints | None = None,
) -> tuple[tuple[str, tuple[object, ...]], ...]:
    """Assert program normal forms suffice while allowing compiler collections."""

    if input_kind == "program":
        raise AssertionError("finite point axes must not bind program inputs")
    return _BIND_DOMAIN_INPUTS(
        materializer,
        execution_id,
        input_kind,
        input_ids,
        ordinals,
        max_points=max_points,
        coverage=coverage,
    )


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
) -> LocalEffectInspection:
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
    ordered_effects = (
        *lowered.compute_operations,
        *(effect for group in lowered.effect_operations for effect in group),
    )
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
    return LocalEffectInspection(
        points=project_run_point_catalog(linked_points).points,
        effects=ordered_effects,
        resource_order=resource_order,
        resource_claims=claims,
        preamble_operations=target.run_operations,
    )


def operations_of_type[T: LocalOperation](
    inspection: LocalEffectInspection,
    operation_type: type[T],
    *,
    point_index: int | None = None,
) -> tuple[T, ...]:
    """Select operations, optionally restricted to one logical point."""

    return tuple(
        effect.operation
        for effect in inspection.effects
        if (point_index is None or point_index in effect.point_indices)
        and isinstance(effect.operation, operation_type)
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
        linked_points.linked_plan.program.record_uses,
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
            linked_points.linked_plan.program.record_uses,
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
    return LinkedPointMaterializer(
        link_program(resolved.experiment, environment)
    ).materialize()
