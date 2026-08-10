"""High-level notebook client for one daemon-owned lab project."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Self, cast
from uuid import uuid4

from scopecat.api._config import LabConfigOperations
from scopecat.api._control import LabControlOperations
from scopecat.api._instruments import LabInstrumentOperations
from scopecat.api._remote import RemoteRunOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.run import RunHandle, run_handle_id
from scopecat.authoring.experiments import Experiment, ExperimentInvocation
from scopecat.config.candidates import CandidateConfig
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import DaemonHealth
from scopecat.measurements.results import Dataset
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.program.values import MetadataValue
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource, RunManifest, RunStageLineage
from scopecat.runs.selectors import RunSelector

type ExperimentSpec = ExperimentInvocation | Experiment[...]
_RUN_PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class ExperimentStage:
    """One durable run in a notebook-driven staged experiment."""

    sequence_id: str
    index: int
    run: RunHandle
    history: tuple[RunHandle, ...]

    @property
    def previous_run(self) -> RunHandle | None:
        return None if self.index == 0 else self.history[-2]

    def measurements(self, *, selector: str = "raw-measurements") -> Dataset:
        """Load this completed stage's labeled measurement dataset."""

        return self.run.measurements(selector=selector)


type NextExperimentStage = Callable[[ExperimentStage], ExperimentSpec | None]


@dataclass(frozen=True, slots=True)
class StagedExperiment:
    """Durable runs belonging to one staged notebook sequence."""

    sequence_id: str
    stages: tuple[ExperimentStage, ...]
    stopped_by_limit: bool | None = None

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

    def staged_experiments(self) -> tuple[StagedExperiment, ...]:
        """Rediscover durable staged experiments, newest sequence first."""

        grouped: dict[str, list[RunManifest]] = {}
        for manifest in self._staged_manifests():
            lineage = manifest.stage
            assert lineage is not None
            grouped.setdefault(lineage.sequence_id, []).append(manifest)
        return tuple(
            self._staged_experiment(sequence_id, manifests)
            for sequence_id, manifests in grouped.items()
        )

    def get_staged_experiment(self, sequence_id: str) -> StagedExperiment:
        """Load one durable staged experiment by its sequence identity."""

        if not sequence_id:
            raise ValueError("sequence_id must be non-empty")
        manifests = self._staged_manifests(sequence_id=sequence_id)
        if not manifests:
            raise KeyError(f"staged experiment not found: {sequence_id}")
        return self._staged_experiment(sequence_id, list(manifests))

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
        and carry explicit typed sequence lineage in their request and manifest.
        When ``max_stages`` is reached, the callback is not called for the
        final completed stage; resuming calls it with that latest stage.
        """

        if max_stages < 1:
            raise ValueError("max_stages must be positive")
        selected_sequence_id = uuid4().hex if sequence_id is None else sequence_id
        if not selected_sequence_id:
            raise ValueError("sequence_id must be non-empty")
        if sequence_id is not None and self._staged_manifests(
            sequence_id=selected_sequence_id
        ):
            raise ValueError(
                f"staged experiment already exists: {selected_sequence_id}; "
                "use resume_staged()"
            )

        prepared = self.prepare(experiment, config=config)
        return self._execute_staged(
            sequence_id=selected_sequence_id,
            current=prepared.invocation,
            next_stage=next_stage,
            max_stages=max_stages,
            config=prepared.config,
            config_source=prepared.config_source,
            completed=(),
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def resume_staged(
        self,
        sequence_id: str,
        *,
        next_stage: NextExperimentStage,
        max_stages: int = 10,
    ) -> StagedExperiment:
        """Continue a rediscovered sequence from its latest successful run.

        ``max_stages`` bounds newly executed stages. The accepted config,
        config source, ordinary request metadata, and operator are inherited
        from the latest durable stage. Resume first calls ``next_stage`` with
        that latest stage, including when the prior execution stopped at its
        limit. If this execution reaches its own limit, its final callback is
        likewise deferred until a later resume.
        """

        if max_stages < 1:
            raise ValueError("max_stages must be positive")
        existing = self.get_staged_experiment(sequence_id)
        latest_manifest = existing.latest.manifest
        if latest_manifest.status != "completed":
            raise ValueError("the latest staged run must be completed before resume")
        following = next_stage(existing.stages[-1])
        if following is None:
            return replace(existing, stopped_by_limit=False)
        latest_request = existing.latest.request
        return self._execute_staged(
            sequence_id=sequence_id,
            current=_experiment_invocation(following),
            next_stage=next_stage,
            max_stages=max_stages,
            config=existing.latest.config,
            config_source=latest_manifest.config_source,
            completed=existing.stages,
            name=None,
            tags=(),
            description=None,
            metadata=cast(
                "Mapping[str, MetadataValue]",
                latest_request.metadata,
            ),
            operator=latest_request.operator,
        )

    def _execute_staged(
        self,
        *,
        sequence_id: str,
        current: ExperimentInvocation,
        next_stage: NextExperimentStage,
        max_stages: int,
        config: ConfigProfileSnapshot,
        config_source: RunConfigSource | None,
        completed: tuple[ExperimentStage, ...],
        name: str | None,
        tags: tuple[str, ...],
        description: str | None,
        metadata: Mapping[str, MetadataValue] | None,
        operator: str | None,
    ) -> StagedExperiment:
        selected = list(completed)
        start_index = len(selected)
        previous_run_id = None if not selected else selected[-1].run.id
        for relative_index in range(max_stages):
            index = start_index + relative_index
            lineage = RunStageLineage(
                sequence_id=sequence_id,
                index=index,
                previous_run_id=previous_run_id,
            )
            run = self.execute_invocation(
                current,
                config=config,
                config_source=config_source,
                name=name,
                tags=tags,
                description=description,
                metadata=metadata,
                operator=operator,
                stage=lineage,
                submission_id=_stage_submission_id(sequence_id, index),
            )
            stage = ExperimentStage(
                sequence_id=sequence_id,
                index=index,
                run=run,
                history=(*(item.run for item in selected), run),
            )
            selected.append(stage)
            if relative_index == max_stages - 1:
                break
            following = next_stage(stage)
            if following is None:
                return StagedExperiment(
                    sequence_id=sequence_id,
                    stages=tuple(selected),
                    stopped_by_limit=False,
                )
            current = _experiment_invocation(following)
            previous_run_id = run.id
        return StagedExperiment(
            sequence_id=sequence_id,
            stages=tuple(selected),
            stopped_by_limit=True,
        )

    def _staged_experiment(
        self,
        sequence_id: str,
        manifests: list[RunManifest],
    ) -> StagedExperiment:
        by_index: dict[int, RunManifest] = {}
        for manifest in manifests:
            lineage = manifest.stage
            assert lineage is not None
            if lineage.index in by_index:
                raise ValueError(
                    f"staged experiment {sequence_id!r} repeats index {lineage.index}"
                )
            by_index[lineage.index] = manifest
        if sorted(by_index) != list(range(len(by_index))):
            raise ValueError(
                f"staged experiment {sequence_id!r} indices must be contiguous "
                "from zero"
            )
        ordered = [by_index[index] for index in range(len(by_index))]
        if any(
            manifest.config_content_hash != ordered[0].config_content_hash
            for manifest in ordered[1:]
        ):
            raise ValueError(
                f"staged experiment {sequence_id!r} uses multiple configurations"
            )
        for index, manifest in enumerate(ordered):
            lineage = manifest.stage
            assert lineage is not None
            expected_previous = None if index == 0 else ordered[index - 1].run_id
            if lineage.previous_run_id != expected_previous:
                raise ValueError(
                    f"staged experiment {sequence_id!r} has a broken predecessor "
                    f"at index {index}"
                )
        runs = tuple(
            RunHandle(session=self, id=manifest.run_id) for manifest in ordered
        )
        return StagedExperiment(
            sequence_id=sequence_id,
            stages=tuple(
                ExperimentStage(
                    sequence_id=sequence_id,
                    index=index,
                    run=run,
                    history=runs[: index + 1],
                )
                for index, run in enumerate(runs)
            ),
        )

    def _staged_manifests(
        self,
        *,
        sequence_id: str | None = None,
    ) -> tuple[RunManifest, ...]:
        manifests: list[RunManifest] = []
        before: int | None = None
        while True:
            page = self._control.run_stages(
                limit=_RUN_PAGE_SIZE,
                before=before,
                sequence_id=sequence_id,
            )
            manifests.extend(item.manifest for item in page.items)
            if page.next_cursor is None:
                return tuple(manifests)
            before = page.next_cursor

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
        stage: RunStageLineage | None = None,
        submission_id: str | None = None,
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
            stage=stage,
            submission_id=submission_id,
        )
        return RunHandle(session=self, id=manifest.run_id)


def _experiment_invocation(experiment: ExperimentSpec) -> ExperimentInvocation:
    return experiment.bind() if isinstance(experiment, Experiment) else experiment


def _stage_submission_id(sequence_id: str, index: int) -> str:
    return f"staged:{sequence_id}:{index}"


__all__ = [
    "ExperimentStage",
    "LabClient",
    "PreparedLabExperiment",
    "StagedExperiment",
]
