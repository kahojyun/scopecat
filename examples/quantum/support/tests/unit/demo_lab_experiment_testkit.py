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
from scopecat.config.candidates import (
    CandidateConfig,
)
from scopecat.config.changes import prepare_parameter_change_approval
from scopecat.config.registry import service as config_registry_service
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.kernel.quantity import Quantity
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystem
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeApprovalRecord
from scopecat.runs.selectors import RunSelector
from tests.testkit.runtime import (
    ServiceRunOperations,
    admit_test_run,
    check_experiment,
    plan_experiment,
    sqlite_execution_session,
    sqlite_project_services,
)

from quantum_lab_demo.compiler import QuantumLabCompiler
from quantum_lab_demo.configuration import quantum_lab_bootstrap_config
from quantum_lab_demo.lab import quantum_lab_system

from .demo_lab_test_paths import (
    EXPERIMENT_VIRTUAL_LAB_PROFILE as TEST_VIRTUAL_LAB_PROFILE,
)

PathInput = str | Path


@dataclass(frozen=True, slots=True)
class _ConfigActivation:
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True, slots=True)
class _RegisteredConfigActivation:
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True, slots=True)
class InProcessPreparedExperiment:
    """Test invocation executed directly below the daemon boundary."""

    lab: InProcessQuantumLab
    invocation: ExperimentInvocation
    config: str | ConfigProfileSnapshot | CandidateConfig
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
            system=self.system,
        )

    def preview(self) -> ExperimentPreview:
        result = self.check()
        assert result.preview is not None, result.problems
        return result.preview

    def run(self) -> RunHandle:
        planned = plan_experiment(
            self.invocation,
            services=self.lab.services,
            config=self.config,
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
        )
        return self.lab.get_run(manifest.run_id)


@dataclass(frozen=True, slots=True)
class InProcessQuantumLab:
    """Quantum integration harness; user workflows use the project daemon."""

    project_root: Path
    services: ProjectStateServices
    config: str | ConfigProfileSnapshot
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
            system=self.system if system is None else system,
        )

    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        return RunHandle(session=self, id=run_handle_id(run))

    def review_parameter_proposal(
        self,
        run: RunSelector | RunHandle,
        selector: str,
        *,
        reviewer: str | None = None,
        note: str = "",
    ) -> ParameterChangeApprovalRecord:
        prepared = prepare_parameter_change_approval(
            run_id=run_handle_id(run),
            selector=selector,
            services=self.services,
            actor=reviewer or self.reviewer,
            note=note,
        )
        if prepared.publication is not None:
            self.services.runs.publish_content(prepared.publication)
        return prepared.approval

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
    ) -> _RegisteredConfigActivation:
        selected_generation = (
            config_registry_service.current_config_registry_generation(
                unit_of_work=self.services.config_registry
            )
            if expected_generation is None
            else expected_generation
        )
        entry, active_state, activation = (
            config_registry_service.register_and_activate_candidate_config(
                unit_of_work=self.services.config_registry,
                entry_id=entry_id,
                registered_by=registered_by or self.operator,
                run_id=candidate.source_run_id,
                proposal_id=candidate.proposal_id,
                operator=operator or self.operator,
                expected_generation=selected_generation,
                note=note,
                activation_note=activation_note,
            )
        )
        return _RegisteredConfigActivation(
            entry=entry,
            active_state=active_state,
            activation=activation,
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
    ) -> _RegisteredConfigActivation:
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
        return _RegisteredConfigActivation(
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
    config_profile: ConfigProfileSnapshot | None = None,
    virtual_lab_profile: PathInput = TEST_VIRTUAL_LAB_PROFILE,
    compiler: QuantumLabCompiler | None = None,
) -> InProcessQuantumLab:
    """Compose isolated storage for unit tests that do not exercise the daemon."""

    config = (
        quantum_lab_bootstrap_config() if config_profile is None else config_profile
    )
    return InProcessQuantumLab(
        project_root=Path(project_root),
        services=sqlite_project_services(project_root),
        config=config,
        system=quantum_lab_system(
            config=config,
            virtual_lab_profile=virtual_lab_profile,
            compiler=compiler,
        ),
    )
