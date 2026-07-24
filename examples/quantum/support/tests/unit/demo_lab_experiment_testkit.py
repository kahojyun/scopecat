from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from scopecat.api.run import (
    RunHandle,
    RunOperations,
    run_handle_id,
)
from scopecat.application.services import ProjectServices
from scopecat.authoring import ExperimentInvocation, ExperimentTemplate, ValueRef
from scopecat.authoring.scans import Scan, ScanCenter, ScanValue
from scopecat.compiler.frontend.environment import (
    ValidatedConfigEnvironment,
    validate_config_environment,
)
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    LinkedPointMaterializer,
    MaterializedLinkedPoints,
    link_verified_program,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.config.candidates import CandidateConfig
from scopecat.config.changes import review_parameter_change_proposal
from scopecat.config.profiles import load_config_profile
from scopecat.config.resolution import (
    ConfigActivation,
    ConfigProfileInput,
    RegisteredConfigActivation,
    register_and_activate_candidate_config,
    register_and_activate_config_profile,
    resolve_experiment_config,
    rollback_config,
)
from scopecat.execution.local.program import ComputeOperation, LocalOperation
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
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
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.local_effects import (
    MaterializedLocalEffects as LocalEffects,
)
from scopecat.planning.local_effects import local_operation_resource_claims
from scopecat.planning.local_materialization import (
    materialize_local_execution,
    prepare_local_target,
)
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from scopecat.records.parameter_change import (
    ParameterChangeDecisionRecord,
    ParameterChangeReviewState,
)
from scopecat.runs.selectors import RunSelector
from scopecat.runs.service import check_experiment, list_runs, run_experiment
from scopecat.testing import ServiceRunOperations, sqlite_project_services

from quantum_lab_demo.compiler import QuantumLabCompiler, QuantumRealtimeLabCompiler
from quantum_lab_demo.lab import quantum_lab_config_profile, quantum_lab_system

from .demo_lab_test_paths import EXPERIMENT_FIXTURE_DIR
from .demo_lab_test_paths import (
    EXPERIMENT_VIRTUAL_LAB_PROFILE as TEST_VIRTUAL_LAB_PROFILE,
)

PathInput = str | Path


@dataclass(frozen=True, slots=True)
class InProcessPreparedExperiment:
    """Test invocation executed directly below the daemon boundary."""

    lab: InProcessQuantumLab
    invocation: ExperimentInvocation
    config: str | ConfigProfileSnapshot | CandidateConfig
    config_profile: ConfigProfileInput | None
    system: ExperimentSystem | None

    def scan(
        self,
        target: ValueRef | Scan,
        values: Sequence[ScanValue] = (),
        *,
        unit: str | None = None,
        center: ScanCenter | None = None,
        span: Quantity | str | None = None,
        points: int | None = None,
    ) -> InProcessPreparedExperiment:
        return replace(
            self,
            invocation=self.invocation.scan(
                target,
                values,
                unit=unit,
                center=center,
                span=span,
                points=points,
            ),
        )

    def check(self) -> ExperimentCheckResult:
        return check_experiment(
            prepare_invocation(self.invocation),
            services=self.lab.services,
            config=self.config,
            config_profile=self.config_profile,
            system=self.system,
        )

    def preview(self) -> ExperimentPreview:
        result = self.check()
        assert result.preview is not None, result.problems
        return result.preview

    def run(
        self,
        *,
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
    ) -> RunHandle:
        manifest = run_experiment(
            prepare_invocation(self.invocation),
            services=self.lab.services,
            config=self.config,
            config_profile=self.config_profile,
            system=self.system,
            event_sink=event_sink,
            payload_observer=payload_observer,
        )
        return self.lab.get_run(manifest.run_id)


@dataclass(frozen=True, slots=True)
class InProcessQuantumLab:
    """Quantum integration harness; user workflows use the project daemon."""

    project_root: Path
    services: ProjectServices
    config: str | ConfigProfileSnapshot
    config_profile: ConfigProfileInput | None
    system: ExperimentSystem | None
    reviewer: str = "operator"
    operator: str = "operator"

    @property
    def run_operations(self) -> RunOperations:
        return ServiceRunOperations(self.services)

    def prepare(
        self,
        experiment: ExperimentInvocation | ExperimentTemplate,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
        system: ExperimentSystem | None = None,
    ) -> InProcessPreparedExperiment:
        invocation = (
            experiment.bind()
            if isinstance(experiment, ExperimentTemplate)
            else experiment
        )
        return InProcessPreparedExperiment(
            lab=self,
            invocation=invocation,
            config=self.config if config is None else config,
            config_profile=(
                self.config_profile
                if config is None and config_profile is None
                else config_profile
            ),
            system=self.system if system is None else system,
        )

    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        return RunHandle(session=self, id=run_handle_id(run))

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, id=manifest.run_id)
            for manifest in list_runs(services=self.services)
        )

    def resolve_config(
        self,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigProfileSnapshot:
        selected = self.config if config is None else config
        return resolve_experiment_config(
            services=self.services,
            config=selected,
            config_profile=self.config_profile if config is None else None,
        ).config

    def review_parameter_proposal(
        self,
        run: RunSelector | RunHandle,
        selector: str,
        *,
        reviewer: str | None = None,
        decision: ParameterChangeReviewState = "approved",
        note: str = "",
    ) -> ParameterChangeDecisionRecord:
        return review_parameter_change_proposal(
            run_id=run_handle_id(run),
            selector=selector,
            services=self.services,
            state=decision,
            reviewer=reviewer or self.reviewer,
            note=note,
        )

    def activate(
        self,
        candidate: CandidateConfig,
        *,
        entry_id: str | None = None,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
        activation_note: str | None = None,
        expected_generation: int | None = None,
    ) -> RegisteredConfigActivation:
        return register_and_activate_candidate_config(
            candidate=candidate,
            services=self.services,
            entry_id=entry_id,
            registered_by=registered_by or self.operator,
            operator=operator or self.operator,
            note=note,
            activation_note=activation_note,
            expected_generation=expected_generation,
        )

    def activate_config(
        self,
        config: ConfigProfileSnapshot,
        *,
        entry_id: str,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
        activation_note: str | None = None,
        expected_generation: int | None = None,
    ) -> RegisteredConfigActivation:
        return register_and_activate_config_profile(
            config=config,
            services=self.services,
            entry_id=entry_id,
            registered_by=registered_by or self.operator,
            operator=operator or self.operator,
            note=note,
            activation_note=activation_note,
            expected_generation=expected_generation,
        )

    def rollback(
        self,
        *,
        expected_generation: int,
        operator: str | None = None,
        note: str = "",
    ) -> ConfigActivation:
        return rollback_config(
            services=self.services,
            operator=operator or self.operator,
            expected_generation=expected_generation,
            note=note,
        )


def in_process_quantum_lab(
    *,
    project_root: PathInput,
    config_profile: PathInput | ConfigProfileSnapshot | None = None,
    virtual_lab_profile: PathInput = TEST_VIRTUAL_LAB_PROFILE,
    compiler: QuantumLabCompiler | QuantumRealtimeLabCompiler | None = None,
) -> InProcessQuantumLab:
    """Compose isolated storage for unit tests that do not exercise the daemon."""

    config = quantum_lab_config_profile(config_profile)
    return InProcessQuantumLab(
        project_root=Path(project_root),
        services=sqlite_project_services(project_root),
        config="active",
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
