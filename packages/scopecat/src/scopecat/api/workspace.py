"""Notebook-first workspace facade for experiment notebooks and scripts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
from scopecat.api.analysis import (
    Analysis,
    AnalysisContext,
    AnalysisInput,
    AnalysisOutput,
    AnalysisStep,
    SavedAnalysis,
)
from scopecat.api.data import Data
from scopecat.api.run import (
    RunHandle,
    run_handle_id,
)
from scopecat.application.services import WorkspaceServices
from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_runtime_input,
    freeze_runtime_inputs,
)
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.scans import (
    Scan,
    ScanCenter,
    ScanValue,
)
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
)
from scopecat.authoring.values import (
    MetadataValue,
    RuntimeInput,
    runtime_input_is_valid,
)
from scopecat.compiler.frontend.invocation import (
    PreparedInvocation,
    prepare_invocation,
)
from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_snapshot,
)
from scopecat.config.changes import (
    ParameterChangeDecisionRecord,
    ParameterChangeReviewState,
    review_parameter_change_proposal,
)
from scopecat.config.resolution import (
    ConfigActivation,
    ConfigProfileInput,
    RegisteredConfigActivation,
    register_and_activate_candidate_config,
    register_and_activate_config_profile,
    resolve_config_source,
    rollback_config,
)
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from scopecat.runs.selectors import RunSelector
from scopecat.runs.service import (
    check_experiment,
    list_runs,
    load_run,
    run_experiment,
)


@dataclass(frozen=True)
class _RunOptions:
    name: str | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None
    inputs: Mapping[str, RuntimeInput] = field(default_factory=empty_frozen_mapping)
    scans: tuple[Scan, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)
    operator: str | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.name is None
            and not self.tags
            and self.description is None
            and not self.inputs
            and not self.scans
            and not self.metadata
            and self.operator is None
        )


@dataclass(frozen=True, slots=True, repr=False)
class PreparedExperiment:
    """Workspace-bound invocation whose terminal methods perform side effects.

    Inputs and scans accumulate immutably until a terminal
    method is called. Keeping `preview()`, `validate()`, and `run()` at the end
    makes the exploratory notebook path read like a plan before anything is
    compiled or executed.
    """

    _session: Workspace
    _prepared_invocation: PreparedInvocation
    _config: str | ConfigProfileSnapshot | CandidateConfig | None = None
    _config_profile: ConfigProfileInput | None = None
    _system: ExperimentSystem | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _run_options: _RunOptions = field(default_factory=_RunOptions)

    def input(self, id: str, value: RuntimeInput) -> PreparedExperiment:  # noqa: A002
        if not id or not runtime_input_is_valid(value):
            msg = "experiment inputs require a non-empty id and closed runtime data"
            raise TypeError(msg)
        inputs = dict(self._run_options.inputs)
        inputs[id] = cast("RuntimeInput", freeze_runtime_input(value))
        return replace(
            self,
            _run_options=replace(
                self._run_options,
                inputs=cast(
                    "Mapping[str, RuntimeInput]",
                    freeze_runtime_inputs(inputs),
                ),
            ),
        )

    def inputs(self, **inputs: RuntimeInput) -> PreparedExperiment:
        invalid = sorted(
            input_id
            for input_id, value in inputs.items()
            if not input_id or not runtime_input_is_valid(value)
        )
        if invalid:
            msg = "experiment inputs require closed runtime data: " + ", ".join(
                repr(input_id) for input_id in invalid
            )
            raise TypeError(msg)
        selected = dict(self._run_options.inputs)
        selected.update(inputs)
        return replace(
            self,
            _run_options=replace(
                self._run_options,
                inputs=cast(
                    "Mapping[str, RuntimeInput]",
                    freeze_runtime_inputs(selected),
                ),
            ),
        )

    def scan(
        self,
        target: ValueRef | Scan,
        values: Sequence[ScanValue] = (),
        *,
        unit: str | None = None,
        center: ScanCenter | None = None,
        span: Quantity | str | None = None,
        points: int | None = None,
    ) -> PreparedExperiment:
        return replace(
            self,
            _prepared_invocation=replace(
                self._prepared_invocation,
                invocation=self._prepared_invocation.invocation.scan(
                    target,
                    values,
                    unit=unit,
                    center=center,
                    span=span,
                    points=points,
                ),
            ),
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
        run_options = _validated_run_options(
            self._run_options,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return _preview_prepared(
            self._session,
            self._prepared_invocation,
            config=self._config,
            config_profile=self._config_profile,
            run_options=run_options,
            system=self._system,
        )

    def check(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentCheckResult:
        """Check authoring, configuration, and planning without execution."""

        run_options = _validated_run_options(
            self._run_options,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return _check_prepared(
            self._session,
            self._prepared_invocation,
            config=self._config,
            config_profile=self._config_profile,
            run_options=run_options,
            system=self._system,
        )

    def run(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
    ) -> RunHandle:
        run_options = _validated_run_options(
            self._run_options,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return _run_prepared(
            self._session,
            self._prepared_invocation,
            config=self._config,
            config_profile=self._config_profile,
            system=self._system,
            run_options=run_options,
            event_sink=event_sink,
            payload_observer=payload_observer,
        )


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class Workspace:
    """Primary vNext workspace facade for lab notebook workflows."""

    _workspace: Path
    services: WorkspaceServices
    _config: str | ConfigProfileSnapshot
    _config_profile: ConfigProfileInput | None
    _system: ExperimentSystem | None
    _reviewer: str
    _operator: str

    def __copy__(self) -> Workspace:
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> Workspace:
        return self

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def config(self) -> str | ConfigProfileSnapshot:
        return self._config

    @property
    def config_profile(self) -> ConfigProfileInput | None:
        return self._config_profile

    @property
    def system(self) -> ExperimentSystem | None:
        return self._system

    @property
    def reviewer(self) -> str:
        return self._reviewer

    @property
    def operator(self) -> str:
        return self._operator

    def resolve_config(
        self,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> ConfigProfileSnapshot:
        """Resolve a configuration selection to its authoritative snapshot."""

        if isinstance(config, CandidateConfig):
            config = resolve_candidate_config_snapshot(
                config,
                services=self.services,
            )
        selected_config = self.config if config is None else config
        selected_config_profile = _effective_config_profile(
            self,
            config=config,
            config_profile=config_profile,
        )
        if isinstance(selected_config, ConfigProfileSnapshot):
            if selected_config_profile is not None:
                msg = "provide either config or config_profile, not both"
                raise ValueError(msg)
            return selected_config
        config_entry = (
            None
            if selected_config_profile is not None and selected_config == "active"
            else selected_config
        )
        resolved = resolve_config_source(
            services=self.services,
            config_profile=selected_config_profile,
            config_entry=config_entry,
        )
        return resolved.config

    def prepare(
        self,
        experiment: ExperimentInvocation | ExperimentTemplate,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
        system: ExperimentSystem | None = None,
    ) -> PreparedExperiment:
        invocation = (
            experiment.bind()
            if isinstance(experiment, ExperimentTemplate)
            else experiment
        )
        prepared_invocation = prepare_invocation(invocation)
        return PreparedExperiment(
            _session=self,
            _prepared_invocation=prepared_invocation,
            _config=config,
            _config_profile=config_profile,
            _system=system,
        )

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, id=manifest.run_id)
            for manifest in list_runs(services=self.services)
        )

    def get_run(self, run: RunSelector) -> RunHandle:
        manifest = load_run(run_id=run_handle_id(run), services=self.services)
        return RunHandle(session=self, id=manifest.run_id)

    def review_parameter_proposal(
        self,
        run: RunHandle | RunSelector,
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
        """Register and atomically select one direct configuration snapshot."""

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
        """Atomically restore the previous distinct active registry entry."""

        return rollback_config(
            services=self.services,
            operator=operator or self.operator,
            expected_generation=expected_generation,
            note=note,
        )


def _prepared_config_selection(
    session: Workspace,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
) -> tuple[
    str | ConfigProfileSnapshot | CandidateConfig,
    ConfigProfileInput | None,
]:
    if config is None:
        selected_config: str | ConfigProfileSnapshot | CandidateConfig = session.config
        config_profile_selector: str | ConfigProfileSnapshot | None = None
    else:
        selected_config = config
        config_profile_selector = (
            None if isinstance(config, CandidateConfig) else config
        )
    if isinstance(selected_config, CandidateConfig):
        # Candidate resolution reads durable run state. Keep it lazy so the
        # workflow can complete config-free authoring before that I/O.
        return selected_config, config_profile
    return selected_config, _effective_config_profile(
        session,
        config=config_profile_selector,
        config_profile=config_profile,
    )


def _effective_config_profile(
    session: Workspace,
    *,
    config: str | ConfigProfileSnapshot | None,
    config_profile: ConfigProfileInput | None,
) -> ConfigProfileInput | None:
    if config is None and config_profile is None:
        return session.config_profile
    return config_profile


def _preview_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    run_options: _RunOptions,
    system: ExperimentSystem | None,
) -> ExperimentPreview:
    result = _check_prepared(
        session,
        prepared_invocation,
        config=config,
        config_profile=config_profile,
        run_options=run_options,
        system=system,
    )
    if result.preview is None:
        raise CheckFailed(result.problems)
    return result.preview


def _check_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    run_options: _RunOptions,
    system: ExperimentSystem | None,
) -> ExperimentCheckResult:
    selected_config, selected_config_profile = _prepared_config_selection(
        session,
        config=config,
        config_profile=config_profile,
    )
    return check_experiment(
        _prepared_invocation_with_run_options(
            prepared_invocation,
            options=run_options,
        ),
        services=session.services,
        config=selected_config,
        config_profile=selected_config_profile,
        system=(session.system if system is None else system),
    )


def _run_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    system: ExperimentSystem | None,
    run_options: _RunOptions,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> RunHandle:
    selected_config, selected_config_profile = _prepared_config_selection(
        session,
        config=config,
        config_profile=config_profile,
    )
    selected_system = session.system if system is None else system
    return RunHandle(
        session=session,
        id=run_experiment(
            _prepared_invocation_with_run_options(
                prepared_invocation,
                options=run_options,
            ),
            services=session.services,
            config=selected_config,
            config_profile=selected_config_profile,
            system=selected_system,
            event_sink=event_sink,
            payload_observer=payload_observer,
        ).run_id,
    )


def _prepared_invocation_with_run_options(
    prepared: PreparedInvocation,
    *,
    options: _RunOptions,
) -> PreparedInvocation:
    if options.is_empty:
        return prepared
    invocation = prepared.invocation
    if options.inputs:
        invocation = invocation.bind(**options.inputs)
    for scan in options.scans:
        invocation = invocation.scan(scan)
    return replace(
        prepared,
        invocation=invocation,
        request_context=replace(
            prepared.request_context,
            metadata=_run_metadata_with_options(
                prepared.request_context.metadata,
                options,
            ),
            operator=options.operator or prepared.request_context.operator,
        ),
    )


def _run_metadata_with_options(
    metadata: Mapping[str, object],
    options: _RunOptions,
) -> dict[str, object]:
    selected = dict(metadata)
    selected.update(options.metadata)
    if options.name is not None:
        selected["name"] = options.name
    if options.tags:
        selected["tags"] = list(options.tags)
    if options.description is not None:
        selected["description"] = options.description
    return selected


def _merged_run_metadata(
    existing: Mapping[str, MetadataValue],
    selected: Mapping[str, MetadataValue] | None,
) -> Mapping[str, MetadataValue]:
    return cast(
        "Mapping[str, MetadataValue]",
        freeze_json_mapping({**existing, **dict(selected or {})}),
    )


def _validated_run_options(
    existing: _RunOptions,
    *,
    name: str | None,
    tags: tuple[str, ...],
    description: str | None,
    metadata: Mapping[str, MetadataValue] | None,
    operator: str | None,
) -> _RunOptions:
    return replace(
        existing,
        name=name,
        tags=tags,
        description=description,
        metadata=_merged_run_metadata(existing.metadata, metadata),
        operator=operator if operator is not None else existing.operator,
    )


__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisInput",
    "AnalysisOutput",
    "AnalysisStep",
    "CandidateConfig",
    "Data",
    "EarlyStopDecision",
    "PreparedExperiment",
    "Quantity",
    "RunHandle",
    "SavedAnalysis",
    "Workspace",
    "decide_online_convergence",
]
