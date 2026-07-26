from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from scopecat.api.run import (
    RunHandle,
    RunOperations,
    run_handle_id,
)
from scopecat.authoring import ExperimentInvocation, ExperimentTemplate, ValueRef
from scopecat.authoring.scans import Scan, ScanCenter, ScanValue
from scopecat.compiler.environment import ConfigEnvironment
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.linking.linked import (
    link_program as link_core_program,
)
from scopecat.compiler.measurement_projection import (
    project_measurement_catalog,
    project_run_point_catalog,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.config.candidates import CandidateConfig
from scopecat.config.changes import prepare_parameter_change_review
from scopecat.config.environment import build_config_environment
from scopecat.config.registry import service as config_registry_service
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
)
from scopecat.config.resolution import (
    ConfigProfileInput,
    RegisteredConfigActivation,
    register_and_activate_candidate_config,
    resolve_experiment_config,
)
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.execution.local.program import ComputeOperation, LocalOperation
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.execution.program import RunCoverageEffect
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.points import RunPoint
from scopecat.measurements.projection import (
    MeasurementProjection,
    select_measurement_projection,
)
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
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import (
    ParameterChangeDecisionRecord,
    ParameterChangeReviewState,
)
from scopecat.runs.selectors import RunSelector
from tests.testkit.runtime import (
    ServiceRunOperations,
    admit_test_run,
    check_experiment,
    list_test_runs,
    plan_experiment,
    sqlite_execution_session,
    sqlite_project_services,
)

from quantum_lab_demo.compiler import QuantumLabCompiler, QuantumRealtimeLabCompiler
from quantum_lab_demo.configuration import quantum_lab_bootstrap_config
from quantum_lab_demo.lab import quantum_lab_config_profile, quantum_lab_system

from .demo_lab_test_paths import (
    EXPERIMENT_VIRTUAL_LAB_PROFILE as TEST_VIRTUAL_LAB_PROFILE,
)

PathInput = str | Path


@dataclass(frozen=True, slots=True)
class _ConfigActivation:
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


def link_invocation(
    invocation: ExperimentInvocation,
    *,
    config_profile: ConfigProfileSnapshot,
) -> LinkedPlan:
    return resolve_compiled_invocation(
        compile_invocation(invocation),
        environment=build_config_environment(config_profile),
    )


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
            self.invocation,
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
        planned = plan_experiment(
            self.invocation,
            services=self.lab.services,
            config=self.config,
            config_profile=self.config_profile,
            system=self.system,
        )
        accepted = admit_test_run(
            config=planned.config,
            request=planned.request,
            repository=self.lab.services.runs,
            config_source=planned.config_source,
        )
        manifest = execute_admitted_run(
            program=planned.program,
            session=sqlite_execution_session(
                self.lab.project_root,
                accepted.run_id,
            ),
            instrument_provider=(
                None if planned.system is None else planned.system.provider
            ),
            event_sink=event_sink,
            payload_observer=payload_observer,
        )
        return self.lab.get_run(manifest.run_id)


@dataclass(frozen=True, slots=True)
class InProcessQuantumLab:
    """Quantum integration harness; user workflows use the project daemon."""

    project_root: Path
    services: ProjectStateServices
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
        experiment: ExperimentInvocation | ExperimentTemplate[...],
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
            for manifest in list_test_runs(self.services.runs)
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
        prepared = prepare_parameter_change_review(
            run_id=run_handle_id(run),
            selector=selector,
            services=self.services,
            state=decision,
            reviewer=reviewer or self.reviewer,
            note=note,
        )
        self.services.runs.publish_content(prepared.publication)
        return prepared.decision

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
        selected_generation = (
            config_registry_service.current_config_registry_generation(
                unit_of_work=self.services.config_registry
            )
            if expected_generation is None
            else expected_generation
        )
        entry, active_state, activation = (
            config_registry_service.register_and_activate_config_profile(
                config=config,
                unit_of_work=self.services.config_registry,
                entry_id=entry_id,
                registered_by=registered_by or self.operator,
                operator=operator or self.operator,
                note=note,
                activation_note=activation_note,
                expected_generation=selected_generation,
            )
        )
        return RegisteredConfigActivation(
            entry=entry,
            active_state=active_state,
            activation=activation,
        )

    def rollback(
        self,
        *,
        expected_generation: int,
        operator: str | None = None,
        note: str = "",
    ) -> _ConfigActivation:
        active_state, activation = config_registry_service.rollback_config_registry(
            unit_of_work=self.services.config_registry,
            operator=operator or self.operator,
            expected_generation=expected_generation,
            note=note,
        )
        return _ConfigActivation(
            active_state=active_state,
            activation=activation,
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


def load_experiment_config() -> ConfigProfileSnapshot:
    return quantum_lab_bootstrap_config()


def link_program(
    program: CoreProgram,
    environment: ConfigEnvironment,
) -> LinkedPlan:
    """Link an externally constructed test program."""

    return link_core_program(program, environment)


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
    resolved = link_invocation(invocation, config_profile=selected_config)
    environment = replace(
        build_config_environment(selected_config),
        parameters=resolved.environment.parameters,
    )
    return materialize_linked_points(link_program(resolved.program, environment))
