"""High-level notebook client for one daemon-owned lab project."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Self
from uuid import uuid4

from scopecat.api._config import LabConfigOperations
from scopecat.api._control import LabControlOperations
from scopecat.api._instruments import LabInstrumentOperations
from scopecat.api._remote import RemoteRunOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.run import RunHandle, run_handle_id
from scopecat.authoring.templates import ExperimentInvocation, ExperimentTemplate
from scopecat.config.candidates import CandidateConfig
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import DaemonHealth
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.program.values import MetadataValue
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource
from scopecat.runs.selectors import RunSelector

type ExperimentSpec = ExperimentInvocation | ExperimentTemplate[...]


@dataclass(frozen=True, slots=True)
class ExperimentStage:
    """One completed run in a notebook-driven staged experiment."""

    sequence_id: str
    index: int
    run: RunHandle
    history: tuple[RunHandle, ...]

    @property
    def previous_run(self) -> RunHandle | None:
        return None if self.index == 0 else self.history[-2]


type NextExperimentStage = Callable[[ExperimentStage], ExperimentSpec | None]


@dataclass(frozen=True, slots=True)
class StagedExperiment:
    """Completed durable runs produced by one staged notebook loop."""

    sequence_id: str
    stages: tuple[ExperimentStage, ...]
    stopped_by_limit: bool = False

    @property
    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(stage.run for stage in self.stages)

    @property
    def latest(self) -> RunHandle:
        return self.stages[-1].run


@dataclass(frozen=True, slots=True)
class PreparedLabExperiment:
    """A config-bound invocation ready for local planning and daemon execution."""

    lab: LabClient
    invocation: ExperimentInvocation
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None

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
        experiment: ExperimentSpec,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> PreparedLabExperiment:
        invocation = _experiment_invocation(experiment)
        resolved_config, config_source = self._config.resolve_with_source(config)
        return PreparedLabExperiment(
            lab=self,
            invocation=invocation,
            config=resolved_config,
            config_source=config_source,
        )

    def preview(
        self,
        experiment: ExperimentSpec,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        """Preview an experiment without requiring an explicit prepare step."""

        return self.prepare(experiment, config=config).preview(
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def run(
        self,
        experiment: ExperimentSpec,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunHandle:
        """Run an experiment directly; use ``prepare`` when reusing a config."""

        return self.prepare(experiment, config=config).run(
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def run_staged(
        self,
        experiment: ExperimentSpec,
        *,
        next_stage: NextExperimentStage,
        max_stages: int = 10,
        sequence_id: str | None = None,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> StagedExperiment:
        """Run a bounded sequence whose next point domain uses prior results.

        Each stage is an ordinary durable run. The callback receives its
        completed :class:`ExperimentStage` and returns the next invocation, or
        ``None`` to finish. All stages use one resolved configuration snapshot
        and carry explicit sequence lineage in their request metadata.
        """

        if max_stages < 1:
            raise ValueError("max_stages must be positive")
        selected_sequence_id = sequence_id or uuid4().hex
        if not selected_sequence_id:
            raise ValueError("sequence_id must be non-empty")

        prepared = self.prepare(experiment, config=config)
        current = prepared.invocation
        completed: list[ExperimentStage] = []
        previous_run_id: str | None = None
        for index in range(max_stages):
            run = self.execute_invocation(
                current,
                config=prepared.config,
                config_source=prepared.config_source,
                name=name,
                tags=tags,
                description=description,
                metadata=_staged_metadata(
                    metadata,
                    sequence_id=selected_sequence_id,
                    index=index,
                    previous_run_id=previous_run_id,
                ),
                operator=operator,
            )
            stage = ExperimentStage(
                sequence_id=selected_sequence_id,
                index=index,
                run=run,
                history=(*(item.run for item in completed), run),
            )
            completed.append(stage)
            following = next_stage(stage)
            if following is None:
                return StagedExperiment(
                    sequence_id=selected_sequence_id,
                    stages=tuple(completed),
                )
            current = _experiment_invocation(following)
            previous_run_id = run.id
        return StagedExperiment(
            sequence_id=selected_sequence_id,
            stages=tuple(completed),
            stopped_by_limit=True,
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


def _experiment_invocation(experiment: ExperimentSpec) -> ExperimentInvocation:
    return (
        experiment.bind() if isinstance(experiment, ExperimentTemplate) else experiment
    )


def _staged_metadata(
    metadata: Mapping[str, MetadataValue] | None,
    *,
    sequence_id: str,
    index: int,
    previous_run_id: str | None,
) -> dict[str, MetadataValue]:
    return {
        **dict(metadata or {}),
        "scopecat_stage": {
            "sequence_id": sequence_id,
            "index": index,
            "previous_run_id": previous_run_id,
        },
    }


__all__ = [
    "ExperimentStage",
    "LabClient",
    "PreparedLabExperiment",
    "StagedExperiment",
]
