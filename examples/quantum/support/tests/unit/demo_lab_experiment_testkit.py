from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from scopecat.api.run import (
    RunHandle,
    RunOperations,
    run_handle_id,
)
from scopecat.authoring import Experiment, ExperimentInvocation
from scopecat.authoring.scans import Axis
from scopecat.config.candidates import (
    CandidateConfig,
)
from scopecat.config.changes import prepare_parameter_change_approval
from scopecat.config.registry import service as config_registry_service
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.planning.system import ExperimentSystem
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot, instrument_bindings
from scopecat.records.parameter_change import ParameterChangeApprovalRecord
from scopecat.runs.selectors import RunSelector
from scopecat.sdk.instruments import InstrumentBackend, InstrumentProviderContext
from tests.testkit.instrument_host import provision_test_instrument_host
from tests.testkit.planning import TestExperimentSystemBuilder
from tests.testkit.runtime import (
    ServiceRunOperations,
    admit_test_run,
    check_experiment,
    plan_experiment,
    sqlite_execution_session,
    sqlite_project_services,
)

from quantum_lab_demo.backend import create_quantum_lab_backend
from quantum_lab_demo.configuration import quantum_lab_bootstrap_config
from quantum_lab_demo.lab import quantum_lab_system

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
    system: ExperimentSystem | None
    build_experiment_system: TestExperimentSystemBuilder | None

    def grid(
        self,
        *axes: Axis,
    ) -> InProcessPreparedExperiment:
        return replace(
            self,
            invocation=self.invocation.grid(*axes),
        )

    def check(self) -> ExperimentCheckResult:
        return check_experiment(
            self.invocation,
            services=self.lab.services,
            config=self.config,
            system=self.system,
            build_experiment_system=self.build_experiment_system,
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
            build_experiment_system=self.build_experiment_system,
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
                instruments=provision_test_instrument_host(
                    self.lab.instrument_backend,
                    context=InstrumentProviderContext(
                        bindings=instrument_bindings(planned.config)
                    ),
                    instrument_ids=planned.program.resource_order,
                ),
            ),
        )
        return self.lab.get_run(manifest.run_id)


@dataclass(frozen=True, slots=True)
class InProcessQuantumLab:
    """Quantum integration harness; user workflows use the project daemon."""

    project_root: Path
    services: ProjectStateServices
    config: str | ConfigProfileSnapshot
    instrument_backend: InstrumentBackend
    reviewer: str = "operator"
    operator: str = "operator"

    @property
    def run_operations(self) -> RunOperations:
        return ServiceRunOperations(self.services)

    def prepare(
        self,
        experiment: ExperimentInvocation | Experiment[...],
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        system: ExperimentSystem | None = None,
    ) -> InProcessPreparedExperiment:
        invocation = (
            experiment.bind() if isinstance(experiment, Experiment) else experiment
        )
        selected_config = self.config if config is None else config
        return InProcessPreparedExperiment(
            lab=self,
            invocation=invocation,
            config=selected_config,
            system=system,
            build_experiment_system=(
                self._system_for_config if system is None else None
            ),
        )

    def _system_for_config(
        self,
        config: ConfigProfileSnapshot,
    ) -> ExperimentSystem:
        provider = self.instrument_backend.provider
        return quantum_lab_system(
            config=config,
            instrument_catalog=resolve_instrument_contract_catalog(
                config=config,
                provider_id=provider.provider_id,
                describe=provider.describe,
            ),
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

    def publish(
        self,
        candidate: CandidateConfig,
        *,
        entry_id: str | None = None,
        actor: str | None = None,
        note: str = "",
        expected_generation: int | None = None,
    ) -> config_registry_service.ConfigRegistryMutationResult:
        selected_generation = (
            config_registry_service.current_config_registry_generation(
                unit_of_work=self.services.config_registry
            )
            if expected_generation is None
            else expected_generation
        )
        selected_actor = actor or self.operator
        return config_registry_service.publish_config_revision(
            revision=config_registry_service.ConfigRevision(
                source=config_registry_service.CandidateConfigRevisionSource(
                    run_id=candidate.source_run_id,
                    proposal_id=candidate.proposal_id,
                ),
                entry_id=entry_id,
                actor=selected_actor,
                note=note,
            ),
            unit_of_work=self.services.config_registry,
            expected_generation=selected_generation,
        )

    def publish_config(
        self,
        config: ConfigProfileSnapshot,
        *,
        entry_id: str,
        actor: str | None = None,
        note: str = "",
        expected_generation: int | None = None,
    ) -> config_registry_service.ConfigRegistryMutationResult:
        selected_generation = (
            config_registry_service.current_config_registry_generation(
                unit_of_work=self.services.config_registry
            )
            if expected_generation is None
            else expected_generation
        )
        selected_actor = actor or self.operator
        return config_registry_service.publish_config_revision(
            revision=config_registry_service.ConfigRevision(
                source=config_registry_service.DirectConfigRevisionSource(config),
                entry_id=entry_id,
                actor=selected_actor,
                note=note,
            ),
            unit_of_work=self.services.config_registry,
            expected_generation=selected_generation,
        )

    def undo(
        self,
        *,
        expected_generation: int,
        actor: str | None = None,
        note: str = "",
    ) -> config_registry_service.ConfigRegistryMutationResult:
        return config_registry_service.undo_config_registry(
            unit_of_work=self.services.config_registry,
            actor=actor or self.operator,
            expected_generation=expected_generation,
            note=note,
        )


def in_process_quantum_lab(
    *,
    project_root: PathInput,
    config_profile: ConfigProfileSnapshot | None = None,
    virtual_lab_profile: PathInput = TEST_VIRTUAL_LAB_PROFILE,
) -> InProcessQuantumLab:
    """Compose isolated storage for unit tests that do not exercise the daemon."""

    config = (
        quantum_lab_bootstrap_config() if config_profile is None else config_profile
    )
    instrument_backend = create_quantum_lab_backend(virtual_lab_profile)
    return InProcessQuantumLab(
        project_root=Path(project_root),
        services=sqlite_project_services(project_root),
        config=config,
        instrument_backend=instrument_backend,
    )
