"""Notebook-first workspace facade for experiment notebooks and scripts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

import scopecat.authoring as authoring
from scopecat._workflows.comparison import compare_runs
from scopecat._workflows.config import (
    ConfigProfileInput,
    RegisteredConfigActivation,
    ResolvedConfig,
    register_and_activate_candidate_config,
    resolve_config_source,
)
from scopecat._workflows.runs import (
    ExperimentInput,
    list_runs,
    load_run,
    preview_experiment,
    run_experiment,
    validate_experiment,
)
from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
from scopecat.authoring import (
    ExperimentInvocation,
    ExperimentModule,
    ExperimentTemplate,
    ModuleBuilder,
    RecordIntent,
    TemplateBuilder,
)
from scopecat.authoring.assembly import (
    WorkspaceExperimentBuilder,
    workspace_experiment_builder,
    workspace_experiment_module,
)
from scopecat.authoring.expressions import Expression
from scopecat.candidate_configs import (
    CandidateConfig,
    CandidateConfigInput,
    resolve_candidate_config,
)
from scopecat.experiments import (
    ComputeNodeFunction,
    ExperimentSpec,
    RunRequest,
    ScanItem,
    ScanRecord,
    delete_param_rows,
    insert_param_rows,
    set_param,
    update_param_rows,
)
from scopecat.instruments import RuntimeEventSink, RuntimePayloadObserver
from scopecat.instruments.sdk import InstrumentProvider
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.parameter_changes import (
    ParameterChangeDecisionRecord,
    ParameterChangeReviewState,
    review_parameter_changes,
)
from scopecat.preview import PreviewExperimentResult, ValidateExperimentResult
from scopecat.relations import ScalarExpr
from scopecat.results import MeasurementDType
from scopecat.run_overview import RunOverview, build_run_overview
from scopecat.run_selectors import RunSelector
from scopecat.session_analysis import (
    Analysis,
    AnalysisContext,
    AnalysisInput,
    AnalysisOutput,
    AnalysisStep,
    SavedAnalysis,
)
from scopecat.session_comparison import ComparisonHandle
from scopecat.session_data import Data
from scopecat.session_run_handle import (
    RunHandle,
    run_handle_id,
)
from scopecat.system_overview import SystemSummary, build_system_summary

type ExperimentSource = ExperimentSpec | ExperimentModule | ModuleBuilder
type ExperimentModuleSource = ExperimentModule | ModuleBuilder
type PublicExperimentInput = ExperimentInput | ExperimentTemplate | TemplateBuilder


@dataclass(frozen=True)
class _RunOptions:
    name: str | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None
    inputs: dict[str, object] = field(default_factory=dict)
    scans: tuple[ScanItem, ...] = ()
    overrides: dict[str, object] = field(default_factory=dict)
    seeds: dict[str, int] = field(default_factory=dict)
    extra_records: dict[str, object] = field(default_factory=dict)
    execution_flags: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    operator: str | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.name is None
            and not self.tags
            and self.description is None
            and not self.inputs
            and not self.scans
            and not self.overrides
            and not self.seeds
            and not self.extra_records
            and not self.execution_flags
            and not self.metadata
            and self.operator is None
        )


@dataclass(frozen=True)
class PreparedExperiment:
    """Workspace-bound invocation whose terminal methods perform side effects.

    Inputs and scans accumulate immutably until a terminal
    method is called. Keeping `preview()`, `validate()`, `resolve()`, and
    `run()` at the end makes the exploratory notebook path read like a plan
    before anything is compiled or executed.
    """

    session: Workspace
    experiment: PublicExperimentInput | Experiment
    config: str | ConfigProfileSnapshot | CandidateConfig | None = None
    config_profile: ConfigProfileInput | None = None
    instrument_provider: InstrumentProvider | None = None
    run_options: _RunOptions = field(default_factory=_RunOptions)

    def input(self, id: str, value: object) -> PreparedExperiment:  # noqa: A002
        inputs = dict(self.run_options.inputs)
        inputs[id] = value
        return replace(
            self,
            run_options=replace(self.run_options, inputs=inputs),
        )

    def inputs(self, **inputs: object) -> PreparedExperiment:
        selected = dict(self.run_options.inputs)
        selected.update(inputs)
        return replace(
            self,
            run_options=replace(self.run_options, inputs=selected),
        )

    def scan(
        self,
        target: str | ScanItem,
        values: Sequence[object] = (),
        *,
        unit: str | None = None,
        center: ScalarExpr | None = None,
        span: Expression | Quantity | str | None = None,
        points: int | None = None,
    ) -> PreparedExperiment:
        return replace(
            self,
            experiment=_scan_prepared_experiment(
                self.experiment,
                target,
                values,
                unit=unit,
                center=center,
                span=span,
                points=points,
            ),
        )

    def preview(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
        description: str | None = None,
        overrides: Mapping[str, object] | None = None,
        seeds: Mapping[str, int] | None = None,
        extra_records: Mapping[str, object] | None = None,
        execution_flags: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        operator: str | None = None,
    ) -> PreviewExperimentResult:
        run_options = replace(
            self.run_options,
            name=name,
            tags=tuple(tags),
            description=description,
            overrides={**self.run_options.overrides, **dict(overrides or {})},
            seeds={**self.run_options.seeds, **dict(seeds or {})},
            extra_records={
                **self.run_options.extra_records,
                **dict(extra_records or {}),
            },
            execution_flags={
                **self.run_options.execution_flags,
                **dict(execution_flags or {}),
            },
            metadata={**self.run_options.metadata, **dict(metadata or {})},
            operator=operator or self.run_options.operator,
        )
        return _preview_prepared(
            self.session,
            self.experiment,
            config=self.config,
            config_profile=self.config_profile,
            run_options=run_options,
        )

    def validate(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
        description: str | None = None,
        overrides: Mapping[str, object] | None = None,
        seeds: Mapping[str, int] | None = None,
        extra_records: Mapping[str, object] | None = None,
        execution_flags: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        operator: str | None = None,
    ) -> ValidateExperimentResult:
        run_options = replace(
            self.run_options,
            name=name,
            tags=tuple(tags),
            description=description,
            overrides={**self.run_options.overrides, **dict(overrides or {})},
            seeds={**self.run_options.seeds, **dict(seeds or {})},
            extra_records={
                **self.run_options.extra_records,
                **dict(extra_records or {}),
            },
            execution_flags={
                **self.run_options.execution_flags,
                **dict(execution_flags or {}),
            },
            metadata={**self.run_options.metadata, **dict(metadata or {})},
            operator=operator or self.run_options.operator,
        )
        return _validate_prepared(
            self.session,
            self.experiment,
            config=self.config,
            config_profile=self.config_profile,
            run_options=run_options,
        )

    def resolve(self) -> ExperimentSpec:
        return _resolve_prepared(
            self.session,
            self.experiment,
            run_options=self.run_options,
            config=self.config,
            config_profile=self.config_profile,
        )

    def run(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
        description: str | None = None,
        overrides: Mapping[str, object] | None = None,
        seeds: Mapping[str, int] | None = None,
        extra_records: Mapping[str, object] | None = None,
        execution_flags: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        operator: str | None = None,
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
    ) -> RunHandle:
        run_options = replace(
            self.run_options,
            name=name,
            tags=tuple(tags),
            description=description,
            overrides={**self.run_options.overrides, **dict(overrides or {})},
            seeds={**self.run_options.seeds, **dict(seeds or {})},
            extra_records={
                **self.run_options.extra_records,
                **dict(extra_records or {}),
            },
            execution_flags={
                **self.run_options.execution_flags,
                **dict(execution_flags or {}),
            },
            metadata={**self.run_options.metadata, **dict(metadata or {})},
            operator=operator or self.run_options.operator,
        )
        return _run_prepared(
            self.session,
            self.experiment,
            config=self.config,
            config_profile=self.config_profile,
            instrument_provider=self.instrument_provider,
            run_options=run_options,
            event_sink=event_sink,
            payload_observer=payload_observer,
        )


@dataclass(frozen=True)
class Experiment:
    """Notebook-first authoring adapter for scripts and exploratory notebooks."""

    name: str
    source: ExperimentSource | None = None
    session: Workspace | None = field(default=None, compare=False, repr=False)
    entity_inputs: dict[str, object] = field(default_factory=dict)
    sources: tuple[ExperimentSource, ...] = ()
    builder: WorkspaceExperimentBuilder = field(
        default_factory=workspace_experiment_builder
    )

    @property
    def scans(self) -> tuple[ScanItem, ...]:
        return self.builder.scans

    @property
    def records(self) -> tuple[RecordIntent, ...]:
        return self.builder.records

    @property
    def observables(self) -> tuple[str, ...]:
        return self.builder.observables

    def entity(self, input_id: str, entity: object) -> Experiment:
        entity_inputs = dict(self.entity_inputs)
        entity_inputs[input_id] = entity
        return replace(
            self,
            entity_inputs=entity_inputs,
            builder=self.builder.entity(input_id),
        )

    def input(self, input_id: str, value: object) -> Experiment:
        return self.entity(input_id, value)

    def inputs(self, **inputs: object) -> Experiment:
        selected = self
        for input_id, value in inputs.items():
            selected = selected.input(input_id, value)
        return selected

    def use(
        self,
        *sources: ExperimentModuleSource,
    ) -> Experiment:
        return replace(self, sources=(*self.sources, *sources))

    def resource(
        self,
        id: str,  # noqa: A002
        *,
        requires: authoring.ResourceSelector | Sequence[str] = (),
    ) -> Experiment:
        return replace(
            self,
            builder=self.builder.resource(
                id,
                requires=requires,
            ),
        )

    def scan(
        self,
        target: str | ScanItem,
        values: Sequence[object] = (),
        *,
        unit: str | None = None,
        center: ScalarExpr | None = None,
        span: object | None = None,
        points: int | None = None,
    ) -> Experiment:
        return replace(
            self,
            builder=self.builder.scan(
                target,
                values,
                unit=unit,
                center=center,
                span=span,
                points=points,
            ),
        )

    def derive(self, variable_id: str, expression: Expression) -> Experiment:
        return replace(
            self,
            builder=self.builder.derive(variable_id, expression),
        )

    def variable(
        self,
        variable_id: str,
        value: Any,
    ) -> Experiment:
        return replace(
            self,
            builder=self.builder.variable(variable_id, value),
        )

    def bind(
        self,
        port_path: str,
        value: Expression | ScalarExpr | Quantity | float,
    ) -> Experiment:
        return replace(self, builder=self.builder.bind(port_path, value))

    def compute(
        self,
        id: str,  # noqa: A002
        *,
        fn: ComputeNodeFunction,
        inputs: Mapping[str, Any] | None = None,
        route_ports: Sequence[str] = (),
    ) -> Experiment:
        return replace(
            self,
            builder=self.builder.compute(
                id,
                fn=fn,
                inputs=inputs,
                route_ports=route_ports,
            ),
        )

    def bind_compute(self, port_path: str, node_id: str, *, kind: str) -> Experiment:
        return replace(
            self,
            builder=self.builder.bind_compute(port_path, node_id, kind=kind),
        )

    def state_table(
        self,
        table_id: str,
        *,
        field: str,
        value_column: str,
        resource_column: str = "resource_id",
        resource_port: str | None = None,
        route_entity_column: str | None = None,
    ) -> Experiment:
        return replace(
            self,
            builder=self.builder.state_table(
                table_id,
                field=field,
                value_column=value_column,
                resource_column=resource_column,
                resource_port=resource_port,
                route_entity_column=route_entity_column,
            ),
        )

    def record(
        self,
        *record_ids: str,
        resource: str | None = None,
        capability: str | None = None,
        product_key: str | None = None,
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[authoring.RecordAxisIntent] = (),
        metadata: dict[str, Any] | None = None,
    ) -> Experiment:
        return replace(
            self,
            builder=self.builder.record(
                *record_ids,
                resource=resource,
                capability=capability,
                product_key=product_key,
                unit=unit,
                dtype=dtype,
                axes=axes,
                metadata=metadata,
            ),
        )

    def record_product(
        self,
        *product_ids: str,
        record_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Experiment:
        return replace(
            self,
            builder=self.builder.record_product(
                *product_ids,
                record_id=record_id,
                metadata=metadata,
            ),
        )

    def measure(self, *observable_ids: str) -> Experiment:
        return self.record(*observable_ids)

    def preview(self) -> PreviewExperimentResult:
        return self._require_session().prepare(self).preview()

    def validate(self) -> ValidateExperimentResult:
        return self._require_session().prepare(self).validate()

    def resolve(self) -> ExperimentSpec:
        return self._require_session().prepare(self).resolve()

    def run(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
        description: str | None = None,
        metadata: Mapping[str, object] | None = None,
        operator: str | None = None,
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
    ) -> RunHandle:
        return (
            self._require_session()
            .prepare(self)
            .run(
                name=name,
                tags=tags,
                description=description,
                metadata=metadata,
                operator=operator,
                event_sink=event_sink,
                payload_observer=payload_observer,
            )
        )

    def _require_session(self) -> Workspace:
        if self.session is None:
            msg = "workspace experiment terminal methods require lab.experiment(...)"
            raise ValueError(msg)
        return self.session

    def to_input(self) -> ExperimentInput:
        if isinstance(self.source, ExperimentSpec):
            if self.sources or self.builder.has_fragments or self.entity_inputs:
                msg = (
                    "closed ExperimentSpec sources cannot be combined with workspace "
                    "builder fragments"
                )
                raise ValueError(msg)
            return self.source
        sources = _workspace_sources(self)
        if not sources:
            msg = "workspace experiment requires a source, module, scan, or record"
            raise ValueError(msg)
        module_sources = tuple(
            source for source in sources if isinstance(source, ExperimentModule)
        )
        if len(module_sources) != len(sources):
            msg = "workspace experiment sources must be modules"
            raise TypeError(msg)
        invocation = (
            authoring.template(
                "scopecat.workspace.experiment",
                kind=_safe_experiment_id(self.name),
            )
            .experiment_id(_safe_experiment_id(self.name))
            .use(*module_sources)
            .metadata(
                source="workspace_experiment_builder",
                name=self.name,
                **(
                    {"entity_inputs": dict(self.entity_inputs)}
                    if self.entity_inputs
                    else {}
                ),
            )
            .bind()
        )
        request_inputs = _workspace_request_inputs(self)
        return replace(
            invocation,
            request=RunRequest(
                id=f"{_safe_experiment_id(self.name)}.request",
                template_id="scopecat.workspace.experiment",
                template_inputs=request_inputs,
                scans=_workspace_scan_records(self.builder.scans),
            ),
            build_inputs=dict(self.entity_inputs),
        )


@dataclass(frozen=True, kw_only=True)
class Workspace:
    """Primary vNext workspace facade for lab notebook workflows."""

    _workspace: Path
    config: str | ConfigProfileSnapshot = "active"
    config_profile: ConfigProfileInput | None = None
    instrument_provider: InstrumentProvider | None = None
    reviewer: str = "operator"
    operator: str = "operator"

    @property
    def workspace(self) -> Path:
        return self._workspace

    def system(
        self,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> SystemSummary:
        if isinstance(config, CandidateConfig):
            config = resolve_candidate_config(config, workspace=self.workspace).config
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
            return build_system_summary(selected_config)
        config_entry = (
            None
            if selected_config_profile is not None and selected_config == "active"
            else selected_config
        )
        resolved = resolve_config_source(
            workspace=self.workspace,
            config_profile=selected_config_profile,
            config_entry=config_entry,
        )
        return build_system_summary(resolved.config)

    def experiment(
        self,
        name: str,
        source: ExperimentSource | None = None,
    ) -> Experiment:
        return Experiment(name=name, source=source, session=self)

    def prepare(
        self,
        experiment: PublicExperimentInput | Experiment,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
        instrument_provider: InstrumentProvider | None = None,
    ) -> PreparedExperiment:
        return PreparedExperiment(
            session=self,
            experiment=experiment,
            config=config,
            config_profile=config_profile,
            instrument_provider=instrument_provider,
        )

    def compare(
        self,
        baseline: RunHandle | RunSelector,
        candidate: RunHandle | RunSelector,
        *,
        observable: str | None = None,
    ) -> ComparisonHandle:
        baseline_id = run_handle_id(baseline)
        result = compare_runs(
            baseline_run_id=baseline_id,
            candidate_run_id=run_handle_id(candidate),
            workspace=self.workspace,
            observable_id=observable,
        )
        return ComparisonHandle(
            session=self,
            baseline_run_id=baseline_id,
            result=result,
        )

    def overview(self, run: RunHandle | RunSelector) -> RunOverview:
        return build_run_overview(
            run_id=run_handle_id(run),
            workspace=self.workspace,
        )

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, manifest=manifest)
            for manifest in list_runs(workspace=self.workspace)
        )

    def get_run(self, run: RunSelector) -> RunHandle:
        details = load_run(run_id=run_handle_id(run), workspace=self.workspace)
        return RunHandle(session=self, manifest=details.manifest)

    def review_parameter_changes(
        self,
        run: RunHandle | RunSelector,
        selector: str,
        *,
        reviewer: str | None = None,
        decision: ParameterChangeReviewState = "approved",
        note: str = "",
    ) -> ParameterChangeDecisionRecord:
        return review_parameter_changes(
            run_id=run_handle_id(run),
            selector=selector,
            workspace=self.workspace,
            state=decision,
            reviewer=reviewer or self.reviewer,
            note=note,
        )

    def activate(
        self,
        candidate: CandidateConfigInput,
        *,
        entry_id: str | None = None,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
        activation_note: str | None = None,
    ) -> RegisteredConfigActivation:
        return register_and_activate_candidate_config(
            candidate=candidate,
            workspace=self.workspace,
            entry_id=entry_id,
            registered_by=registered_by or self.operator,
            operator=operator or self.operator,
            note=note,
            activation_note=activation_note,
        )


def open(  # noqa: A001
    workspace: str | Path,
    *,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    instrument_provider: InstrumentProvider | None = None,
    reviewer: str = "operator",
    operator: str = "operator",
) -> Workspace:
    return Workspace(
        _workspace=Path(workspace),
        config=config,
        config_profile=config_profile,
        instrument_provider=instrument_provider,
        reviewer=reviewer,
        operator=operator,
    )


def _prepared_config_selection(
    session: Workspace,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
) -> tuple[str | ConfigProfileSnapshot, ConfigProfileInput | None]:
    if config is None:
        selected_config: str | ConfigProfileSnapshot | CandidateConfig = session.config
        config_profile_selector: str | ConfigProfileSnapshot | None = None
    else:
        selected_config = config
        config_profile_selector = (
            None if isinstance(config, CandidateConfig) else config
        )
    if isinstance(selected_config, CandidateConfig):
        selected_config = resolve_candidate_config(
            selected_config,
            workspace=session.workspace,
        ).config
        config_profile_selector = selected_config
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


def _resolve_prepared(
    session: Workspace,
    experiment: PublicExperimentInput | Experiment,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    run_options: _RunOptions,
) -> ExperimentSpec:
    selected_config, selected_config_profile = _prepared_config_selection(
        session,
        config=config,
        config_profile=config_profile,
    )
    prepared = _prepare_public_experiment_input(
        experiment,
        run_options=run_options,
    )
    if isinstance(prepared, ExperimentSpec):
        return prepared
    config_result = _resolve_prepared_config(
        workspace=session.workspace,
        config=selected_config,
        config_profile=selected_config_profile,
    )
    return authoring.resolve_experiment_with_config(
        prepared,
        config=config_result.config,
        workspace=session.workspace,
        config_source=config_result.config_source,
    ).experiment


def _preview_prepared(
    session: Workspace,
    experiment: PublicExperimentInput | Experiment,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    run_options: _RunOptions,
) -> PreviewExperimentResult:
    selected_config, selected_config_profile = _prepared_config_selection(
        session,
        config=config,
        config_profile=config_profile,
    )
    return preview_experiment(
        _prepare_public_experiment_input(experiment, run_options=run_options),
        workspace=session.workspace,
        config=selected_config,
        config_profile=selected_config_profile,
    )


def _validate_prepared(
    session: Workspace,
    experiment: PublicExperimentInput | Experiment,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    run_options: _RunOptions,
) -> ValidateExperimentResult:
    selected_config, selected_config_profile = _prepared_config_selection(
        session,
        config=config,
        config_profile=config_profile,
    )
    return validate_experiment(
        _prepare_public_experiment_input(experiment, run_options=run_options),
        workspace=session.workspace,
        config=selected_config,
        config_profile=selected_config_profile,
    )


def _run_prepared(
    session: Workspace,
    experiment: PublicExperimentInput | Experiment,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    instrument_provider: InstrumentProvider | None,
    run_options: _RunOptions,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> RunHandle:
    selected_config, selected_config_profile = _prepared_config_selection(
        session,
        config=config,
        config_profile=config_profile,
    )
    selected_instrument_provider = (
        session.instrument_provider
        if instrument_provider is None
        else instrument_provider
    )
    return RunHandle(
        session=session,
        manifest=run_experiment(
            _prepare_public_experiment_input(experiment, run_options=run_options),
            workspace=session.workspace,
            config=selected_config,
            config_profile=selected_config_profile,
            instrument_provider=selected_instrument_provider,
            event_sink=event_sink,
            payload_observer=payload_observer,
        ),
    )


def _request_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _request_value(asdict(value))
    if isinstance(value, dict):
        mapping = cast("dict[Any, object]", value)
        return {str(key): _request_value(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return [_request_value(item) for item in sequence]
    return value


def _prepare_public_experiment_input(
    experiment: PublicExperimentInput | Experiment,
    *,
    run_options: _RunOptions,
) -> ExperimentInput:
    if isinstance(experiment, Experiment):
        return _apply_run_options(experiment.to_input(), run_options)
    return _apply_run_options(experiment, run_options)


def _apply_run_options(
    experiment: PublicExperimentInput,
    options: _RunOptions,
) -> ExperimentInput:
    if isinstance(experiment, TemplateBuilder):
        experiment = experiment.build()
    if isinstance(experiment, ExperimentTemplate):
        experiment = experiment.bind(**options.inputs)
        options = replace(options, inputs={})
    if options.is_empty:
        return experiment
    if isinstance(experiment, ExperimentInvocation):
        if options.inputs:
            experiment = experiment.bind(**options.inputs)
        return replace(
            experiment,
            scans=(
                *experiment.scans,
                *options.scans,
            ),
            request=_request_with_options(
                experiment.request,
                options,
            ),
        )
    if options.inputs:
        msg = "closed ExperimentSpec inputs cannot be changed with run-time inputs"
        raise ValueError(msg)
    if options.scans:
        msg = "closed ExperimentSpec inputs cannot be changed with scans"
        raise ValueError(msg)
    request = experiment.request
    if request is None:
        request = RunRequest(id=f"{experiment.id}.request")
    return experiment.model_copy(
        update={
            "request": _request_with_options(
                request,
                options,
            )
        }
    )


def _request_with_options(
    request: RunRequest,
    options: _RunOptions,
) -> RunRequest:
    metadata = dict(request.metadata)
    metadata.update(options.metadata)
    if options.name is not None:
        metadata["name"] = options.name
    if options.tags:
        metadata["tags"] = list(options.tags)
    if options.description is not None:
        metadata["description"] = options.description

    template_inputs = dict(request.template_inputs)

    update: dict[str, object] = {
        "template_inputs": template_inputs,
        "metadata": metadata,
        "run_overrides": {**request.run_overrides, **options.overrides},
        "seeds": {**request.seeds, **options.seeds},
        "extra_records": {**request.extra_records, **options.extra_records},
        "execution_flags": {
            **request.execution_flags,
            **options.execution_flags,
        },
    }
    if options.operator is not None:
        update["operator"] = options.operator
    return request.model_copy(update=update)


def _scan_prepared_experiment(
    experiment: PublicExperimentInput | Experiment,
    target: str | ScanItem,
    values: Sequence[object],
    *,
    unit: str | None,
    center: ScalarExpr | None,
    span: Expression | Quantity | str | None,
    points: int | None,
) -> PublicExperimentInput | Experiment:
    if isinstance(experiment, TemplateBuilder):
        return experiment.bind().scan(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
    if isinstance(experiment, ExperimentTemplate):
        return experiment.bind().scan(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
    if isinstance(experiment, ExperimentInvocation):
        return experiment.scan(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
    if isinstance(experiment, Experiment):
        return experiment.scan(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
    msg = "closed ExperimentSpec inputs cannot be changed with prepared scans"
    raise ValueError(msg)


def _resolve_prepared_config(
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
    if isinstance(config, ConfigProfileSnapshot):
        if config_profile is not None:
            msg = "provide either config or config_profile, not both"
            raise ValueError(msg)
        return ResolvedConfig(config=config)
    config_entry = None if config_profile is not None and config == "active" else config
    return resolve_config_source(
        workspace=workspace,
        config_profile=config_profile,
        config_entry=config_entry,
    )


def _workspace_sources(
    experiment: Experiment,
) -> tuple[ExperimentSpec | ExperimentModule, ...]:
    sources: list[ExperimentSpec | ExperimentModule] = []
    if experiment.source is not None:
        if isinstance(experiment.source, ExperimentSpec):
            return (experiment.source,)
        sources.append(_workspace_compose_source(experiment.source))
    sources.extend(_workspace_compose_source(source) for source in experiment.sources)
    workspace_module = _workspace_module(experiment)
    if workspace_module is not None:
        sources.append(workspace_module)
    return tuple(sources)


def _workspace_compose_source(
    source: ExperimentSource,
) -> ExperimentSpec | ExperimentModule:
    if isinstance(source, ModuleBuilder):
        return source.build()
    return source


def _workspace_module(experiment: Experiment) -> ExperimentModule | None:
    if not experiment.builder.has_fragments:
        return None
    return workspace_experiment_module(
        experiment.builder,
        f"scopecat.workspace.{_safe_experiment_id(experiment.name)}",
        metadata={"source": "workspace_experiment_builder"},
    )


def _workspace_request_inputs(experiment: Experiment) -> dict[str, object]:
    return {
        "name": experiment.name,
        **(
            {"entity_inputs": dict(experiment.entity_inputs)}
            if experiment.entity_inputs
            else {}
        ),
        "sources": [_workspace_source_label(source) for source in experiment.sources],
        "scans": _workspace_scan_records(experiment.builder.scans),
        "records": [
            {
                "id": record.id,
                "resource": record.resource,
                "capability": record.capability,
                "product_key": record.product_key,
                "unit": record.unit,
                "dtype": record.dtype,
            }
            for record in experiment.builder.records
        ],
        "selected_products": [
            {
                "product_id": selection.product_id,
                "record_id": selection.record_id,
            }
            for selection in experiment.builder.record_selections
        ],
    }


def _workspace_scan_records(scans: Sequence[ScanItem]) -> list[ScanRecord]:
    return [scan.request_record() for scan in scans]


def _workspace_source_label(source: object) -> str:
    if isinstance(source, ExperimentModule):
        return source.id
    if isinstance(source, ModuleBuilder):
        return source.id or "module"
    if isinstance(source, ExperimentInvocation):
        return source.request.template_id or source.request.id
    if isinstance(source, ExperimentSpec):
        return source.id
    return type(source).__name__


def _safe_experiment_id(name: str) -> str:
    selected = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-").lower()
    return selected or "experiment"


__all__ = [
    "Analysis",
    "AnalysisContext",
    "AnalysisInput",
    "AnalysisOutput",
    "AnalysisStep",
    "CandidateConfig",
    "ComparisonHandle",
    "Data",
    "EarlyStopDecision",
    "Experiment",
    "PreparedExperiment",
    "Quantity",
    "RecordIntent",
    "RunHandle",
    "SavedAnalysis",
    "Workspace",
    "decide_online_convergence",
    "delete_param_rows",
    "insert_param_rows",
    "open",
    "set_param",
    "update_param_rows",
]
