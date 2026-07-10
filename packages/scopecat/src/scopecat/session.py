"""Notebook-first workspace facade for experiment notebooks and scripts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import scopecat.authoring as authoring
from scopecat._workflows.comparison import compare_runs
from scopecat._workflows.config import (
    ConfigProfileInput,
    RegisteredConfigActivation,
    register_and_activate_candidate_config,
    resolve_config_source,
)
from scopecat._workflows.runs import (
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
from scopecat.authoring._invocation_plan import (
    PreparedInvocation,
    default_request_context,
    prepare_invocation,
)
from scopecat.authoring.expressions import Expression
from scopecat.candidate_configs import (
    CandidateConfig,
    CandidateConfigInput,
    resolve_candidate_config,
)
from scopecat.experiments import (
    ComputeNodeFunction,
    ComputeResultRef,
    ParameterScanAxis,
    ScanAxis,
    ScanGroup,
    ScanItem,
    delete_param_rows,
    insert_param_rows,
    set_param,
    update_param_rows,
)
from scopecat.experiments import (
    axis as scan_axis,
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
from scopecat.relations import RelationExpr, ScalarExpr, param
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
from scopecat.value_types import Scalar


@dataclass(frozen=True)
class _RunOptions:
    name: str | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None
    inputs: dict[str, object] = field(default_factory=dict)
    scans: tuple[ScanItem, ...] = ()
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
            and not self.metadata
            and self.operator is None
        )


@dataclass(frozen=True)
class PreparedExperiment:
    """Workspace-bound invocation whose terminal methods perform side effects.

    Inputs and scans accumulate immutably until a terminal
    method is called. Keeping `preview()`, `validate()`, and `run()` at the end
    makes the exploratory notebook path read like a plan before anything is
    compiled or executed.
    """

    session: Workspace
    prepared_invocation: PreparedInvocation
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
            prepared_invocation=replace(
                self.prepared_invocation,
                invocation=self.prepared_invocation.invocation.scan(
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
        tags: Sequence[str] = (),
        description: str | None = None,
        metadata: Mapping[str, object] | None = None,
        operator: str | None = None,
    ) -> PreviewExperimentResult:
        run_options = replace(
            self.run_options,
            name=name,
            tags=tuple(tags),
            description=description,
            metadata={**self.run_options.metadata, **dict(metadata or {})},
            operator=operator or self.run_options.operator,
        )
        return _preview_prepared(
            self.session,
            self.prepared_invocation,
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
        metadata: Mapping[str, object] | None = None,
        operator: str | None = None,
    ) -> ValidateExperimentResult:
        run_options = replace(
            self.run_options,
            name=name,
            tags=tuple(tags),
            description=description,
            metadata={**self.run_options.metadata, **dict(metadata or {})},
            operator=operator or self.run_options.operator,
        )
        return _validate_prepared(
            self.session,
            self.prepared_invocation,
            config=self.config,
            config_profile=self.config_profile,
            run_options=run_options,
        )

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
        run_options = replace(
            self.run_options,
            name=name,
            tags=tuple(tags),
            description=description,
            metadata={**self.run_options.metadata, **dict(metadata or {})},
            operator=operator or self.run_options.operator,
        )
        return _run_prepared(
            self.session,
            self.prepared_invocation,
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
    session: Workspace | None = field(default=None, compare=False, repr=False)
    entity_inputs: dict[str, object] = field(default_factory=dict)
    module: ModuleBuilder = field(default_factory=ModuleBuilder)
    scans: tuple[ScanItem, ...] = ()
    record_selections: tuple[authoring.ProductSelectionIntent, ...] = ()

    @property
    def records(self) -> tuple[RecordIntent, ...]:
        return self.module.records

    @property
    def observables(self) -> tuple[str, ...]:
        return self.module.observables

    def entity(self, input_id: str, entity: object) -> Experiment:
        entity_inputs = dict(self.entity_inputs)
        entity_inputs[input_id] = entity
        return replace(
            self,
            entity_inputs=entity_inputs,
            module=self.module.entity(input_id),
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
        *modules: ExperimentModule | ModuleBuilder | authoring.ModuleInvocation,
    ) -> Experiment:
        return replace(self, module=self.module.use(*modules))

    def resource(
        self,
        id: str,  # noqa: A002
        *,
        requires: authoring.ResourceSelector | Sequence[str] = (),
    ) -> Experiment:
        return replace(
            self,
            module=self.module.resource(
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
        selected = _workspace_scan_item(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
        return replace(
            self,
            scans=(*self.scans, selected),
        )

    def derive(self, variable_id: str, expression: Expression) -> Experiment:
        return replace(
            self,
            module=self.module.derive(variable_id, expression),
        )

    def variable(
        self,
        variable_id: str,
        value: Any,
    ) -> Experiment:
        return replace(
            self,
            module=self.module.variable(variable_id, value),
        )

    def bind(
        self,
        port_path: str,
        value: Expression | ScalarExpr | ComputeResultRef | Quantity | float,
    ) -> Experiment:
        return replace(self, module=self.module.bind(port_path, value))

    def compute(
        self,
        id: str,  # noqa: A002
        *,
        fn: ComputeNodeFunction,
        inputs: Mapping[str, Any] | None = None,
        route_ports: Sequence[str] = (),
        output_type: Scalar | None = None,
    ) -> Experiment:
        return replace(
            self,
            module=self.module.compute(
                id,
                fn=fn,
                inputs=inputs,
                route_ports=route_ports,
                output_type=output_type,
            ),
        )

    def state_each(
        self,
        relation: RelationExpr,
        *,
        resource: object | None = None,
        resource_port: str | None = None,
        field: str,
        value: object,
        route_entities: Sequence[object] = (),
    ) -> Experiment:
        return replace(
            self,
            module=self.module.state_each(
                relation,
                resource=resource,
                resource_port=resource_port,
                field=field,
                value=value,
                route_entities=route_entities,
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
            module=self.module.record(
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
        selections = tuple(
            authoring.record_product(
                product_id,
                record_id=record_id,
                metadata=metadata,
            )
            for product_id in product_ids
        )
        return replace(
            self,
            record_selections=(*self.record_selections, *selections),
        )

    def measure(self, *observable_ids: str) -> Experiment:
        return self.record(*observable_ids)

    def preview(self) -> PreviewExperimentResult:
        return self._require_session().prepare(self).preview()

    def validate(self) -> ValidateExperimentResult:
        return self._require_session().prepare(self).validate()

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

    def to_invocation(self) -> ExperimentInvocation:
        if not _workspace_experiment_has_fragments(self):
            msg = "workspace experiment requires a source, module, scan, or record"
            raise ValueError(msg)
        experiment_id = _safe_experiment_id(self.name)
        template = _workspace_template(
            self,
            experiment_id=experiment_id,
        )
        return template.bind(**self.entity_inputs)


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

    def experiment(self, name: str) -> Experiment:
        return Experiment(name=name, session=self)

    def prepare(
        self,
        experiment: (
            ExperimentInvocation | ExperimentTemplate | TemplateBuilder | Experiment
        ),
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
        instrument_provider: InstrumentProvider | None = None,
    ) -> PreparedExperiment:
        if isinstance(experiment, TemplateBuilder):
            invocation = experiment.build().bind()
            prepared_invocation = prepare_invocation(invocation)
        elif isinstance(experiment, ExperimentTemplate):
            invocation = experiment.bind()
            prepared_invocation = prepare_invocation(invocation)
        elif isinstance(experiment, Experiment):
            invocation = experiment.to_invocation()
            prepared_invocation = _workspace_prepared_invocation(
                experiment,
                invocation,
            )
        else:
            invocation = experiment
            prepared_invocation = prepare_invocation(invocation)
        return PreparedExperiment(
            session=self,
            prepared_invocation=prepared_invocation,
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


def _preview_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
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
        _prepared_invocation_with_run_options(
            prepared_invocation,
            options=run_options,
        ),
        workspace=session.workspace,
        config=selected_config,
        config_profile=selected_config_profile,
    )


def _validate_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
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
        _prepared_invocation_with_run_options(
            prepared_invocation,
            options=run_options,
        ),
        workspace=session.workspace,
        config=selected_config,
        config_profile=selected_config_profile,
    )


def _run_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
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
            _prepared_invocation_with_run_options(
                prepared_invocation,
                options=run_options,
            ),
            workspace=session.workspace,
            config=selected_config,
            config_profile=selected_config_profile,
            instrument_provider=selected_instrument_provider,
            event_sink=event_sink,
            payload_observer=payload_observer,
        ),
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
    return replace(
        prepared,
        invocation=replace(invocation, scans=(*invocation.scans, *options.scans)),
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


def _workspace_template(
    experiment: Experiment,
    *,
    experiment_id: str,
) -> ExperimentTemplate:
    module = _workspace_module(
        experiment,
        module_id=f"{experiment_id}.module",
    )
    builder = module.template(
        "scopecat.workspace.experiment",
        kind=experiment_id,
        experiment_id=experiment_id,
        metadata={
            "source": "workspace_experiment",
            "name": experiment.name,
            **(
                {"entity_inputs": dict(experiment.entity_inputs)}
                if experiment.entity_inputs
                else {}
            ),
        },
    )
    for scan in experiment.scans:
        builder = builder.scan(scan)
    for selection in experiment.record_selections:
        builder = builder.record_product(
            selection.product_id,
            record_id=selection.record_id,
            metadata=selection.metadata,
        )
    return builder.build()


def _workspace_module(
    experiment: Experiment,
    *,
    module_id: str,
) -> ExperimentModule:
    return replace(experiment.module, id=module_id).build(
        metadata={
            "source": "workspace_experiment",
        },
    )


def _workspace_experiment_has_fragments(experiment: Experiment) -> bool:
    return bool(
        experiment.module.has_fragments
        or experiment.scans
        or experiment.record_selections
    )


def _workspace_request_inputs(experiment: Experiment) -> dict[str, object]:
    return {
        "name": experiment.name,
        **(
            {"entity_inputs": dict(experiment.entity_inputs)}
            if experiment.entity_inputs
            else {}
        ),
        "scans": _workspace_scan_records(experiment.scans),
        "records": [
            {
                "id": record.id,
                "resource": record.resource,
                "capability": record.capability,
                "product_key": record.product_key,
                "unit": record.unit,
                "dtype": record.dtype,
            }
            for record in experiment.module.records
        ],
        "selected_products": [
            {
                "product_id": selection.product_id,
                "record_id": selection.record_id,
            }
            for selection in experiment.record_selections
        ],
    }


def _workspace_prepared_invocation(
    experiment: Experiment,
    invocation: ExperimentInvocation,
) -> PreparedInvocation:
    return prepare_invocation(
        invocation,
        request_context=replace(
            default_request_context(invocation),
            template_inputs=_workspace_request_inputs(experiment),
        ),
    )


def _workspace_scan_records(scans: Sequence[ScanItem]) -> list[object]:
    return [scan.request_record() for scan in scans]


def _workspace_scan_item(
    target: str | ScanItem,
    values: Sequence[object] = (),
    *,
    unit: str | None = None,
    center: ScalarExpr | None = None,
    span: object | None = None,
    points: int | None = None,
) -> ScanItem:
    if isinstance(target, ScanAxis | ParameterScanAxis | ScanGroup):
        if (
            values
            or unit is not None
            or center is not None
            or span is not None
            or points is not None
        ):
            msg = "scan item cannot be combined with scan construction arguments"
            raise ValueError(msg)
        return target
    if values:
        if center is not None or span is not None or points is not None:
            msg = "scan values cannot be combined with center/span/points"
            raise ValueError(msg)
        return scan_axis(target, values=values, unit=unit)
    if span is None or points is None:
        msg = "scan requires values or span and points"
        raise ValueError(msg)
    return scan_axis(
        target,
        center=center or param(target),
        span=_workspace_scan_span_value(span),
        points=points,
    )


def _workspace_scan_span_value(value: object) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if isinstance(value, Expression):
        if value.kind == "quantity" and value.quantity is not None:
            return value.quantity
        msg = "scan span expression must be a quantity"
        raise TypeError(msg)
    if isinstance(value, str):
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([^\s]+)", value.strip())
        if match is not None:
            return Quantity(value=float(match.group(1)), unit=match.group(2))
    msg = f"expected quantity value like '100 MHz', got {value!r}"
    raise TypeError(msg)


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
