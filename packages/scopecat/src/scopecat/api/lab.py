"""High-level notebook client for one daemon-owned lab project."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Literal, Self, cast
from uuid import uuid4

from pydantic import BaseModel

from scopecat.api._config import LabConfigOperations
from scopecat.api._control import LabControlOperations
from scopecat.api._instruments import LabInstrumentOperations
from scopecat.api._remote import RemoteRunOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.run import RunHandle, run_handle_id
from scopecat.authoring.experiments import Experiment, ExperimentInvocation
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.config.candidates import CandidateConfig
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import DaemonHealth
from scopecat.kernel.content_identity import (
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.measurements.results import (
    Dataset,
    ExperimentResultView,
    StoredExperimentResultView,
)
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.program.values import MetadataValue
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import (
    RunConfigSource,
    RunManifest,
    RunSequenceDecision,
    RunSequenceLineage,
    RunSequenceTransition,
)
from scopecat.runs.selectors import RunSelector

type ExperimentSpec = ExperimentInvocation | Experiment[...]
_RUN_PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class SequenceRun:
    """One durable run in a policy-controlled linear sequence."""

    sequence_id: str
    run_index: int
    run: RunHandle
    history: tuple[RunHandle, ...]

    @property
    def previous_run(self) -> RunHandle | None:
        return None if self.run_index == 0 else self.history[-2]

    @property
    def decision(self) -> RunSequenceDecision | None:
        """Return the durable policy decision that selected this run."""

        lineage = self.run.manifest.sequence
        return None if lineage is None else lineage.decision

    def measurements(self, *, selector: str = "raw-measurements") -> Dataset:
        """Load this completed run's labeled measurement dataset."""

        return self.run.measurements(selector=selector)


def _empty_sequence_metadata() -> dict[str, MetadataValue]:
    return {}


@dataclass(frozen=True, slots=True)
class SequenceProposal:
    """One next invocation, optional config, and durable policy state."""

    experiment: ExperimentSpec
    policy_id: str
    policy_version: str
    config: ConfigProfileSnapshot | CandidateConfig | None = None
    decision: Mapping[str, MetadataValue] = field(
        default_factory=_empty_sequence_metadata
    )
    checkpoint: Mapping[str, MetadataValue] = field(
        default_factory=_empty_sequence_metadata
    )

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_version:
            raise ValueError("sequence policy id and version must be non-empty")
        object.__setattr__(self, "decision", freeze_json_mapping(self.decision))
        object.__setattr__(self, "checkpoint", freeze_json_mapping(self.checkpoint))


type NextSequenceRun = Callable[[SequenceRun], ExperimentSpec | SequenceProposal | None]


@dataclass(frozen=True, slots=True)
class RunSequence:
    """Durable runs and transitions in one linear sequence."""

    sequence_id: str
    sequence_runs: tuple[SequenceRun, ...]
    transitions: tuple[RunSequenceTransition, ...] = ()

    @property
    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(sequence_run.run for sequence_run in self.sequence_runs)

    @property
    def latest(self) -> RunHandle:
        return self.sequence_runs[-1].run

    @property
    def status(
        self,
    ) -> Literal[
        "awaiting_decision",
        "proposed",
        "stopped",
        "budget_exhausted",
        "policy_failed",
    ]:
        latest_index = self.sequence_runs[-1].run_index
        latest_transitions = tuple(
            transition
            for transition in self.transitions
            if transition.run_index == latest_index
        )
        if not latest_transitions:
            return "awaiting_decision"
        return latest_transitions[-1].status

    @property
    def is_terminal(self) -> bool:
        return self.status in {"stopped", "budget_exhausted"}

    def results(self, *, selector: str = "raw-measurements") -> SequenceResults:
        """Load one result collection while preserving durable run boundaries."""

        return SequenceResults(
            sequence_id=self.sequence_id,
            sequence_runs=self.sequence_runs,
            selector=selector,
            datasets=tuple(
                sequence_run.measurements(selector=selector)
                for sequence_run in self.sequence_runs
            ),
        )


@dataclass(frozen=True, slots=True)
class SequenceResults:
    """Measurement results from an ordered run sequence."""

    sequence_id: str
    sequence_runs: tuple[SequenceRun, ...]
    datasets: tuple[Dataset, ...]
    selector: str = "raw-measurements"

    @property
    def stored(self) -> tuple[StoredExperimentResultView, ...]:
        """Return each run's self-describing persisted result contract."""

        return tuple(dataset.result for dataset in self.datasets)

    def bind[ResultT](
        self,
        output: ResultT,
        /,
    ) -> tuple[ExperimentResultView[ResultT], ...]:
        """Bind the same authored result schema to every run dataset."""

        return tuple(dataset.bind(output) for dataset in self.datasets)


@dataclass(frozen=True, slots=True)
class _SequenceEvaluation:
    invocation: ExperimentInvocation | None
    decision: RunSequenceDecision | None
    transition: RunSequenceTransition
    config: ConfigProfileSnapshot | None = None
    config_source: RunConfigSource | None = None
    proposal_id: str | None = None


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

    def run_sequences(self) -> tuple[RunSequence, ...]:
        """Rediscover durable run sequences, newest sequence first."""

        grouped: dict[str, list[RunManifest]] = {}
        for manifest in self._sequence_manifests():
            lineage = manifest.sequence
            assert lineage is not None
            grouped.setdefault(lineage.sequence_id, []).append(manifest)
        return tuple(
            self._run_sequence(sequence_id, manifests)
            for sequence_id, manifests in grouped.items()
        )

    def get_run_sequence(self, sequence_id: str) -> RunSequence:
        """Load one durable run sequence by its sequence identity."""

        if not sequence_id:
            raise ValueError("sequence_id must be non-empty")
        manifests = self._sequence_manifests(sequence_id=sequence_id)
        if not manifests:
            raise KeyError(f"run sequence not found: {sequence_id}")
        return self._run_sequence(sequence_id, list(manifests))

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

    def run_sequence(
        self,
        experiment: ExperimentSpec,
        *,
        next_run: NextSequenceRun,
        max_runs: int = 10,
        max_new_runs: int | None = None,
        sequence_id: str | None = None,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunSequence:
        """Run a durable linear sequence whose next run uses prior results.

        Each sequence run is an ordinary durable run. The callback receives its
        completed :class:`SequenceRun` and returns the next invocation, or
        ``None`` to finish. ``max_runs`` is the persistent scientific budget.
        ``max_new_runs`` optionally limits work performed by this call without
        changing that budget.
        """

        _validate_run_budget(max_runs=max_runs, max_new_runs=max_new_runs)
        selected_sequence_id = uuid4().hex if sequence_id is None else sequence_id
        if not selected_sequence_id:
            raise ValueError("sequence_id must be non-empty")
        if sequence_id is not None and self._sequence_manifests(
            sequence_id=selected_sequence_id
        ):
            raise ValueError(
                f"run sequence already exists: {selected_sequence_id}; "
                "use resume_sequence()"
            )

        prepared = self.prepare(experiment, config=config)
        return self._execute_sequence(
            sequence_id=selected_sequence_id,
            current=prepared.invocation,
            current_decision=None,
            current_proposal_id=None,
            next_run=next_run,
            max_runs=max_runs,
            max_new_runs=max_runs if max_new_runs is None else max_new_runs,
            config=prepared.config,
            config_source=prepared.config_source,
            completed=(),
            transitions=(),
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def resume_sequence(
        self,
        sequence_id: str,
        *,
        next_run: NextSequenceRun,
        max_new_runs: int | None = None,
    ) -> RunSequence:
        """Continue a rediscovered sequence from its latest successful run.

        ``max_new_runs`` optionally bounds work performed by this call. The accepted
        persistent run budget, config,
        config source, ordinary request metadata, and operator are inherited
        from the latest durable sequence run. Resume first calls ``next_run`` with
        that latest run when it is awaiting a decision.
        """

        existing = self.get_run_sequence(sequence_id)
        latest_manifest = existing.latest.manifest
        if latest_manifest.status != "completed":
            raise ValueError("the latest sequence run must be completed before resume")
        if existing.is_terminal:
            raise ValueError(f"run sequence is already terminal: {existing.status}")
        if existing.status not in {"awaiting_decision", "proposed"}:
            raise ValueError(
                f"run sequence cannot resume from status: {existing.status}"
            )
        lineage = latest_manifest.sequence
        assert lineage is not None
        max_runs = lineage.max_runs
        remaining_runs = max_runs - len(existing.sequence_runs)
        if remaining_runs < 1:
            raise ValueError("run sequence has exhausted its persistent run budget")
        _validate_run_budget(max_runs=max_runs, max_new_runs=max_new_runs)
        selected_new_runs = (
            remaining_runs
            if max_new_runs is None
            else min(max_new_runs, remaining_runs)
        )
        latest_sequence_run = existing.sequence_runs[-1]
        latest_request = existing.latest.request
        current_config = existing.latest.config
        expected_transition = (
            existing.transitions[-1] if existing.status == "proposed" else None
        )
        selected = self._evaluate_sequence_run(
            latest_sequence_run,
            next_run,
            run_index=len(existing.sequence_runs),
            max_runs=max_runs,
            current_config=current_config,
            current_config_source=latest_manifest.config_source,
            name=latest_request.display_name,
            tags=latest_request.tags,
            description=latest_request.description,
            metadata=cast("Mapping[str, MetadataValue]", latest_request.metadata),
            operator=latest_request.operator,
            ordinal=(
                expected_transition.ordinal
                if expected_transition is not None
                else sum(
                    transition.run_index == latest_sequence_run.run_index
                    for transition in existing.transitions
                )
            ),
            expected_transition=expected_transition,
        )
        transitions = (
            existing.transitions
            if expected_transition is not None
            else (*existing.transitions, selected.transition)
        )
        if selected.invocation is None:
            return RunSequence(
                sequence_id=sequence_id,
                sequence_runs=existing.sequence_runs,
                transitions=transitions,
            )
        assert selected.config is not None
        return self._execute_sequence(
            sequence_id=sequence_id,
            current=selected.invocation,
            current_decision=selected.decision,
            current_proposal_id=selected.proposal_id,
            next_run=next_run,
            max_runs=max_runs,
            max_new_runs=selected_new_runs,
            config=selected.config,
            config_source=selected.config_source,
            completed=existing.sequence_runs,
            transitions=transitions,
            name=latest_request.display_name,
            tags=latest_request.tags,
            description=latest_request.description,
            metadata=cast(
                "Mapping[str, MetadataValue]",
                latest_request.metadata,
            ),
            operator=latest_request.operator,
        )

    def _execute_sequence(
        self,
        *,
        sequence_id: str,
        current: ExperimentInvocation,
        current_decision: RunSequenceDecision | None,
        current_proposal_id: str | None,
        next_run: NextSequenceRun,
        max_runs: int,
        max_new_runs: int,
        config: ConfigProfileSnapshot,
        config_source: RunConfigSource | None,
        completed: tuple[SequenceRun, ...],
        transitions: tuple[RunSequenceTransition, ...],
        name: str | None,
        tags: tuple[str, ...],
        description: str | None,
        metadata: Mapping[str, MetadataValue] | None,
        operator: str | None,
    ) -> RunSequence:
        selected = list(completed)
        recorded_transitions = list(transitions)
        start_index = len(selected)
        previous_run_id = None if not selected else selected[-1].run.id
        remaining_runs = max_runs - start_index
        for relative_index in range(min(max_new_runs, remaining_runs)):
            run_index = start_index + relative_index
            lineage = RunSequenceLineage(
                sequence_id=sequence_id,
                run_index=run_index,
                max_runs=max_runs,
                previous_run_id=previous_run_id,
                proposal_id=current_proposal_id,
                decision=current_decision,
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
                sequence=lineage,
                submission_id=_sequence_submission_id(sequence_id, run_index),
            )
            sequence_run = SequenceRun(
                sequence_id=sequence_id,
                run_index=run_index,
                run=run,
                history=(*(item.run for item in selected), run),
            )
            selected.append(sequence_run)
            if len(selected) == max_runs:
                recorded_transitions.append(
                    _record_sequence_transition(
                        sequence_run,
                        ordinal=0,
                        status="budget_exhausted",
                        details={"max_runs": max_runs},
                    )
                )
                return RunSequence(
                    sequence_id=sequence_id,
                    sequence_runs=tuple(selected),
                    transitions=tuple(recorded_transitions),
                )
            if relative_index == max_new_runs - 1:
                return RunSequence(
                    sequence_id=sequence_id,
                    sequence_runs=tuple(selected),
                    transitions=tuple(recorded_transitions),
                )
            following = self._evaluate_sequence_run(
                sequence_run,
                next_run,
                run_index=run_index + 1,
                max_runs=max_runs,
                current_config=config,
                current_config_source=config_source,
                name=name,
                tags=tags,
                description=description,
                metadata=metadata,
                operator=operator,
                ordinal=0,
            )
            recorded_transitions.append(following.transition)
            if following.invocation is None:
                return RunSequence(
                    sequence_id=sequence_id,
                    sequence_runs=tuple(selected),
                    transitions=tuple(recorded_transitions),
                )
            current = following.invocation
            current_decision = following.decision
            current_proposal_id = following.proposal_id
            assert following.config is not None
            config = following.config
            config_source = following.config_source
            previous_run_id = run.id
        return RunSequence(
            sequence_id=sequence_id,
            sequence_runs=tuple(selected),
            transitions=tuple(recorded_transitions),
        )

    def _evaluate_sequence_run(
        self,
        sequence_run: SequenceRun,
        next_run: NextSequenceRun,
        *,
        run_index: int,
        max_runs: int,
        current_config: ConfigProfileSnapshot,
        current_config_source: RunConfigSource | None,
        name: str | None,
        tags: tuple[str, ...],
        description: str | None,
        metadata: Mapping[str, MetadataValue] | None,
        operator: str | None,
        ordinal: int,
        expected_transition: RunSequenceTransition | None = None,
    ) -> _SequenceEvaluation:
        try:
            proposed = next_run(sequence_run)
            normalized = (
                None
                if proposed is None
                else _next_run(proposed, based_on_run_id=sequence_run.run.id)
            )
            if normalized is None:
                if expected_transition is not None:
                    raise ValueError(
                        "sequence callback no longer reproduces its durable proposal"
                    )
                transition = _record_sequence_transition(
                    sequence_run,
                    ordinal=ordinal,
                    status="stopped",
                    details={"reason": "callback-returned-none"},
                )
                return _SequenceEvaluation(
                    invocation=None,
                    decision=None,
                    transition=transition,
                )
            invocation, decision, proposed_config = normalized
            if proposed_config is None:
                selected_config = current_config
                selected_source = current_config_source
            else:
                selected_config, selected_source = self._config.resolve_with_source(
                    proposed_config
                )
            base_request = compile_invocation(
                invocation,
                display_name=name,
                tags=tags,
                description=description,
                metadata=metadata,
                operator=operator,
            ).request
            selected_config_hash = config_content_hash(selected_config)
            proposal_id = _sequence_proposal_id(
                request=base_request,
                config_content_hash=selected_config_hash,
                sequence_id=sequence_run.sequence_id,
                run_index=run_index,
                previous_run_id=sequence_run.run.id,
                decision=decision,
            )
            lineage = RunSequenceLineage(
                sequence_id=sequence_run.sequence_id,
                run_index=run_index,
                max_runs=max_runs,
                previous_run_id=sequence_run.run.id,
                proposal_id=proposal_id,
                decision=decision,
            )
            request = base_request.model_copy(update={"sequence": lineage})
            transition = RunSequenceTransition(
                sequence_id=sequence_run.sequence_id,
                run_index=sequence_run.run_index,
                ordinal=ordinal,
                based_on_run_id=sequence_run.run.id,
                status="proposed",
                next_experiment_id=invocation.definition.id,
                proposal_id=proposal_id,
                next_request_content_hash=_model_content_hash(request),
                next_config_content_hash=selected_config_hash,
                next_config_source=selected_source,
                decision=decision,
            )
        except Exception as error:
            if expected_transition is None:
                _record_sequence_transition(
                    sequence_run,
                    ordinal=ordinal,
                    status="policy_failed",
                    details={
                        "exception_type": (
                            f"{type(error).__module__}.{type(error).__qualname__}"
                        )
                    },
                )
            raise
        if expected_transition is not None:
            if transition != expected_transition:
                raise ValueError(
                    "sequence callback no longer reproduces its durable proposal"
                )
            transition = expected_transition
        else:
            _attach_sequence_transition(sequence_run, transition)
        return _SequenceEvaluation(
            invocation=invocation,
            decision=decision,
            transition=transition,
            config=selected_config,
            config_source=selected_source,
            proposal_id=proposal_id,
        )

    def _run_sequence(
        self,
        sequence_id: str,
        manifests: list[RunManifest],
    ) -> RunSequence:
        by_index: dict[int, RunManifest] = {}
        for manifest in manifests:
            lineage = manifest.sequence
            assert lineage is not None
            if lineage.run_index in by_index:
                raise ValueError(
                    f"run sequence {sequence_id!r} repeats run index "
                    f"{lineage.run_index}"
                )
            by_index[lineage.run_index] = manifest
        if sorted(by_index) != list(range(len(by_index))):
            raise ValueError(
                f"run sequence {sequence_id!r} indices must be contiguous from zero"
            )
        ordered = [by_index[run_index] for run_index in range(len(by_index))]
        first_lineage = ordered[0].sequence
        assert first_lineage is not None
        max_runs = first_lineage.max_runs
        if any(
            manifest.sequence is None or manifest.sequence.max_runs != max_runs
            for manifest in ordered[1:]
        ):
            raise ValueError(
                f"run sequence {sequence_id!r} changes its persistent run budget"
            )
        for run_index, manifest in enumerate(ordered):
            lineage = manifest.sequence
            assert lineage is not None
            expected_previous = (
                None if run_index == 0 else ordered[run_index - 1].run_id
            )
            if lineage.previous_run_id != expected_previous:
                raise ValueError(
                    f"run sequence {sequence_id!r} has a broken predecessor "
                    f"at run index {run_index}"
                )
        runs = tuple(
            RunHandle(session=self, id=manifest.run_id) for manifest in ordered
        )
        sequence_runs = tuple(
            SequenceRun(
                sequence_id=sequence_id,
                run_index=run_index,
                run=run,
                history=runs[: run_index + 1],
            )
            for run_index, run in enumerate(runs)
        )
        return _sequence_result(
            sequence_id,
            sequence_runs,
            manifests=tuple(ordered),
        )

    def _sequence_manifests(
        self,
        *,
        sequence_id: str | None = None,
    ) -> tuple[RunManifest, ...]:
        manifests: list[RunManifest] = []
        before: int | None = None
        while True:
            page = self._control.run_sequences(
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
        sequence: RunSequenceLineage | None = None,
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
            sequence=sequence,
            submission_id=submission_id,
        )
        return RunHandle(session=self, id=manifest.run_id)


def _experiment_invocation(experiment: ExperimentSpec) -> ExperimentInvocation:
    return experiment.bind() if isinstance(experiment, Experiment) else experiment


def _next_run(
    proposed: ExperimentSpec | SequenceProposal,
    *,
    based_on_run_id: str,
) -> tuple[
    ExperimentInvocation,
    RunSequenceDecision | None,
    ConfigProfileSnapshot | CandidateConfig | None,
]:
    if not isinstance(proposed, SequenceProposal):
        return _experiment_invocation(proposed), None, None
    return (
        _experiment_invocation(proposed.experiment),
        RunSequenceDecision(
            policy_id=proposed.policy_id,
            policy_version=proposed.policy_version,
            based_on_run_id=based_on_run_id,
            decision=proposed.decision,
            checkpoint=proposed.checkpoint,
        ),
        proposed.config,
    )


def _record_sequence_transition(
    sequence_run: SequenceRun,
    *,
    ordinal: int,
    status: Literal[
        "proposed",
        "stopped",
        "budget_exhausted",
        "policy_failed",
    ],
    details: Mapping[str, MetadataValue] | None = None,
) -> RunSequenceTransition:
    transition = RunSequenceTransition(
        sequence_id=sequence_run.sequence_id,
        run_index=sequence_run.run_index,
        ordinal=ordinal,
        based_on_run_id=sequence_run.run.id,
        status=status,
        details=details or {},
    )
    _attach_sequence_transition(sequence_run, transition)
    return transition


def _attach_sequence_transition(
    sequence_run: SequenceRun,
    transition: RunSequenceTransition,
) -> None:
    sequence_run.run.attach(
        key=f"sequence-transition-{sequence_run.run_index}-{transition.ordinal}",
        kind="run-sequence-transition",
        text=transition.model_dump_json(),
        filename=(
            f"sequence-transition-{sequence_run.run_index}-{transition.ordinal}.json"
        ),
        media_type="application/json",
        metadata={
            "sequence_id": sequence_run.sequence_id,
            "run_index": sequence_run.run_index,
            "status": transition.status,
        },
    )


def _sequence_proposal_id(
    *,
    request: BaseModel,
    config_content_hash: str,
    sequence_id: str,
    run_index: int,
    previous_run_id: str,
    decision: RunSequenceDecision | None,
) -> str:
    return "sha256:" + stable_content_hash(
        {
            "request_content_hash": _model_content_hash(request),
            "config_content_hash": config_content_hash,
            "sequence_id": sequence_id,
            "run_index": run_index,
            "previous_run_id": previous_run_id,
            "decision": (
                None if decision is None else decision.model_dump(mode="json")
            ),
        }
    )


def _model_content_hash(model: BaseModel) -> str:
    return "sha256:" + model_wire_content_hash(model)


def _sequence_result(
    sequence_id: str,
    sequence_runs: tuple[SequenceRun, ...],
    *,
    manifests: tuple[RunManifest, ...],
) -> RunSequence:
    transitions = tuple(
        RunSequenceTransition.model_validate(
            sequence_run.run.artifact_json(
                artifact.id,
                expected_kind="run-sequence-transition",
            ).content
        )
        for sequence_run, manifest in zip(sequence_runs, manifests, strict=True)
        for artifact in manifest.artifacts
        if artifact.kind == "run-sequence-transition"
    )
    return RunSequence(
        sequence_id=sequence_id,
        sequence_runs=sequence_runs,
        transitions=transitions,
    )


def _validate_run_budget(
    *,
    max_runs: int,
    max_new_runs: int | None,
) -> None:
    if max_runs < 1:
        raise ValueError("max_runs must be positive")
    if max_new_runs is not None and max_new_runs < 1:
        raise ValueError("max_new_runs must be positive")


def _sequence_submission_id(sequence_id: str, run_index: int) -> str:
    return f"sequence:{sequence_id}:{run_index}"


__all__ = [
    "LabClient",
    "PreparedLabExperiment",
    "RunSequence",
    "SequenceProposal",
    "SequenceResults",
    "SequenceRun",
]
