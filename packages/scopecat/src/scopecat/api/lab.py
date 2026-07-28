"""High-level notebook client for one daemon-owned lab project."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Self

from scopecat.api._config import LabConfigOperations
from scopecat.api._control import LabControlOperations
from scopecat.api._instruments import LabInstrumentOperations
from scopecat.api._remote import RemoteRunOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.run import RunHandle, run_handle_id
from scopecat.authoring.scans import Scan
from scopecat.authoring.templates import ExperimentInvocation, ExperimentTemplate
from scopecat.authoring.values import MetadataValue
from scopecat.config.candidates import CandidateConfig
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import DaemonHealth
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource
from scopecat.runs.selectors import RunSelector


@dataclass(frozen=True, slots=True)
class PreparedLabExperiment:
    """A config-bound invocation ready for local planning and daemon execution."""

    lab: LabClient
    invocation: ExperimentInvocation
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None

    def scan(
        self,
        *scans: Scan,
    ) -> PreparedLabExperiment:
        return replace(
            self,
            invocation=self.invocation.scan(*scans),
        )

    def preview(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        return self.lab.preview_invocation(
            self.invocation,
            config=self.config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def run(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunHandle:
        return self.lab.execute_invocation(
            self.invocation,
            config=self.config,
            config_source=self.config_source,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )


class LabClient:
    """Notebook workflows backed by one daemon HTTP owner."""

    def __init__(
        self,
        daemon: str | DaemonClient,
        *,
        build_experiment_system: ExperimentSystemBuilder | None = None,
        config: ConfigProfileSnapshot | None = None,
        operator: str = "operator",
    ) -> None:
        self._owns_client = isinstance(daemon, str)
        self._client = DaemonClient(daemon) if isinstance(daemon, str) else daemon
        self._runs = RemoteRunOperations(self._client)
        self._config = LabConfigOperations(
            client=self._client,
            runs=self._runs,
            default_config=config,
            operator=operator,
        )
        self._control = LabControlOperations(self._client)
        self._instruments = LabInstrumentOperations(
            self._client,
            operator=operator,
        )
        self._runner = _DaemonRunner(self._client, build_experiment_system)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def run_operations(self) -> RemoteRunOperations:
        return self._runs

    @property
    def config(self) -> LabConfigOperations:
        return self._config

    @property
    def control(self) -> LabControlOperations:
        return self._control

    @property
    def instruments(self) -> LabInstrumentOperations:
        return self._instruments

    def health(self) -> DaemonHealth:
        return self._control.health()

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, id=item.run_id)
            for item in self._control.runs().items
        )

    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        run_id = run_handle_id(run)
        self._control.run_detail(run_id)
        return RunHandle(session=self, id=run_id)

    def resolve_config(
        self,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigProfileSnapshot:
        return self._config.resolve(config)

    def prepare(
        self,
        experiment: ExperimentInvocation | ExperimentTemplate[...],
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> PreparedLabExperiment:
        invocation = (
            experiment.bind()
            if isinstance(experiment, ExperimentTemplate)
            else experiment
        )
        resolved_config, config_source = self._config.resolve_with_source(config)
        return PreparedLabExperiment(
            lab=self,
            invocation=invocation,
            config=resolved_config,
            config_source=config_source,
        )

    def preview_invocation(
        self,
        invocation: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        return self._runner.preview(
            invocation,
            config=config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def execute_invocation(
        self,
        invocation: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot,
        config_source: RunConfigSource | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunHandle:
        manifest = self._runner.run(
            invocation,
            config=config,
            config_source=config_source,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return RunHandle(session=self, id=manifest.run_id)


__all__ = ["LabClient", "PreparedLabExperiment"]
