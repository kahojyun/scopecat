"""Small in-process harness for unit tests below the daemon boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from scopecat.api.run import (
    RunHandle,
    RunOperations,
    run_handle_id,
)
from scopecat.authoring import Axis, Experiment, ExperimentInvocation
from scopecat.config.candidates import CandidateConfig
from scopecat.config.changes import prepare_parameter_change_approval
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.kernel.errors import CheckFailed
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.preview import PreviewCoordinateMode
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.planning.system import ExperimentSystem, ExperimentSystemBuilder
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
    instrument_bindings,
)
from scopecat.records.parameter_change import ParameterChangeApprovalRecord
from scopecat.runs.selectors import RunSelector
from scopecat.sdk.instruments import InstrumentBackend, InstrumentProviderContext

from scopecat_testkit.instrument_host import provision_test_instrument_host
from scopecat_testkit.planning import TestExperimentSystemBuilder
from scopecat_testkit.server.runtime import (
    ServiceRunOperations,
    admit_test_run,
    check_experiment,
    list_test_runs,
    plan_experiment,
    resolve_test_config,
    sqlite_execution_session,
)


@dataclass(frozen=True, slots=True)
class InProcessPreparedExperiment:
    """Unit-test invocation that executes directly through application services."""

    lab: InProcessLab
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

    def preview(
        self,
        *,
        point: int | Literal["first", "middle", "last"] = "first",
        coordinates: Mapping[str, object] | None = None,
        coordinate_mode: PreviewCoordinateMode = "exact",
    ) -> ExperimentPreview:
        result = check_experiment(
            self.invocation,
            services=self.lab.services,
            config=self.config,
            system=self.system,
            build_experiment_system=self.build_experiment_system,
            preview_point=point,
            preview_coordinates=coordinates,
            preview_coordinate_mode=coordinate_mode,
        )
        if result.preview is None:
            raise CheckFailed(result.problems)
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
class InProcessLab:
    """Test-only composition; product workflows must use ``LabClient``."""

    project_root: Path
    services: ProjectStateServices
    config: str | ConfigProfileSnapshot = "active"
    system: ExperimentSystem | None = None
    instrument_backend: InstrumentBackend | None = None
    build_experiment_system: ExperimentSystemBuilder | None = None
    reviewer: str = "operator"

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
    ) -> ExperimentSystem | None:
        catalog = _instrument_catalog(self.instrument_backend, config)
        if self.build_experiment_system is not None:
            return self.build_experiment_system(config, catalog)
        if self.system is None:
            return None
        return replace(self.system, instrument_catalog=catalog)

    def resolve_config(
        self,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigProfileSnapshot:
        selected = self.config if config is None else config
        return resolve_test_config(
            services=self.services,
            config=selected,
        )[0]

    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        return RunHandle(session=self, id=run_handle_id(run))

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, id=manifest.run_id)
            for manifest in list_test_runs(self.services.runs)
        )

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


def in_process_lab(
    project_root: str | Path,
    *,
    config: str | ConfigProfileSnapshot = "active",
    system: ExperimentSystem | None = None,
    instrument_backend: InstrumentBackend | None = None,
    build_experiment_system: ExperimentSystemBuilder | None = None,
) -> InProcessLab:
    from scopecat_testkit.server.runtime import sqlite_project_services

    return InProcessLab(
        project_root=Path(project_root),
        services=sqlite_project_services(project_root),
        config=config,
        system=system,
        instrument_backend=instrument_backend,
        build_experiment_system=build_experiment_system,
    )


def _instrument_catalog(
    backend: InstrumentBackend | None,
    config: ConfigProfileSnapshot,
) -> InstrumentContractCatalog:
    if backend is None:
        return InstrumentContractCatalog(
            config_content_hash=config_content_hash(config),
        )
    return resolve_instrument_contract_catalog(
        config=config,
        provider_id=backend.provider.provider_id,
        describe=backend.provider.describe,
    )
