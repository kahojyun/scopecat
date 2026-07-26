"""Small in-process harness for unit tests below the daemon boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from scopecat.api.run import (
    RunHandle,
    RunOperations,
    run_handle_id,
)
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.scans import Scan, ScanCenter, ScanValue
from scopecat.authoring.templates import ExperimentInvocation, ExperimentTemplate
from scopecat.config.candidates import CandidateConfig
from scopecat.config.changes import prepare_parameter_change_review
from scopecat.config.resolution import (
    ConfigProfileInput,
    resolve_experiment_config,
)
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.quantity import Quantity
from scopecat.planning.check_results import ExperimentCheckResult
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
)


@dataclass(frozen=True, slots=True)
class InProcessPreparedExperiment:
    """Unit-test invocation that executes directly through application services."""

    lab: InProcessLab
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
        if result.preview is None:
            raise CheckFailed(result.problems)
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
class InProcessLab:
    """Test-only composition; product workflows must use ``LabClient``."""

    project_root: Path
    services: ProjectStateServices
    config: str | ConfigProfileSnapshot = "active"
    config_profile: ConfigProfileInput | None = None
    system: ExperimentSystem | None = None
    reviewer: str = "operator"

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
        selected_config = self.config if config is None else config
        selected_profile = (
            self.config_profile
            if config is None and config_profile is None
            else config_profile
        )
        return InProcessPreparedExperiment(
            lab=self,
            invocation=invocation,
            config=selected_config,
            config_profile=selected_profile,
            system=self.system if system is None else system,
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


def in_process_lab(
    project_root: str | Path,
    *,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    system: ExperimentSystem | None = None,
) -> InProcessLab:
    from tests.testkit.runtime import sqlite_project_services

    return InProcessLab(
        project_root=Path(project_root),
        services=sqlite_project_services(project_root),
        config=config,
        config_profile=config_profile,
        system=system,
    )
