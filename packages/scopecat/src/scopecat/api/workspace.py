"""Notebook-first workspace facade for experiment notebooks and scripts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, dataclass, field, replace
from pathlib import Path
from typing import cast

import scopecat.authoring as public_authoring
from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
from scopecat.api._services import workspace_services
from scopecat.api.analysis import (
    Analysis,
    AnalysisContext,
    AnalysisInput,
    AnalysisOutput,
    AnalysisStep,
    SavedAnalysis,
)
from scopecat.api.comparison import ComparisonHandle
from scopecat.api.data import Data
from scopecat.api.run import (
    RunHandle,
    run_handle_id,
)
from scopecat.api.system_overview import SystemSummary, build_system_summary
from scopecat.application.services import WorkspaceServices
from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_runtime_input,
    freeze_runtime_inputs,
)
from scopecat.authoring._handles import create_handle, replace_handle
from scopecat.authoring._module_handles import (
    BindingInput,
    StateRouteInput,
    StateScalarInput,
)
from scopecat.authoring._record_intents import (
    ProductRef,
    ProductSelectionIntent,
    RecordAxis,
    RecordIntent,
    product_selection_intent,
    record_product,
)
from scopecat.authoring.assembly import (
    ExperimentModule,
    ModuleBuilder,
    ModuleInvocation,
)
from scopecat.authoring.scans import (
    Scan,
    ScanCenter,
    ScanValue,
    build_scan,
)
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
    TemplateBuilder,
    template_builder_with_record_selections_internal,
)
from scopecat.authoring.values import (
    Compute,
    MetadataValue,
    RuntimeInput,
    ValueRef,
    runtime_input_is_valid,
)
from scopecat.compiler.frontend.invocation import (
    PreparedInvocation,
    default_request_context,
    prepare_invocation,
)
from scopecat.config.candidates import (
    CandidateConfig,
    CandidateConfigInput,
    resolve_candidate_config_snapshot,
)
from scopecat.config.changes import (
    ParameterChangeDecisionRecord,
    ParameterChangeReviewState,
    review_parameter_change_proposal,
)
from scopecat.config.resolution import (
    ConfigProfileInput,
    RegisteredConfigActivation,
    register_and_activate_candidate_config,
    resolve_config_source,
)
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.measurements.results import MeasurementDType
from scopecat.planning.backend import ExecutionBackend, ExecutionOptions
from scopecat.planning.checks import ExperimentCheckReport
from scopecat.planning.preview_models import (
    PreviewExperimentResult,
    ValidateExperimentResult,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity
from scopecat.run_comparison.service import compare_runs
from scopecat.run_overview import RunOverview, build_run_overview
from scopecat.runs.selectors import RunSelector
from scopecat.runs.service import (
    check_experiment,
    list_runs,
    load_run,
    preview_experiment,
    run_experiment,
    validate_experiment,
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


@dataclass(frozen=True, slots=True, init=False, repr=False)
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
    _execution_backend: ExecutionBackend | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _execution_options: ExecutionOptions | None = None
    _run_options: _RunOptions = field(default_factory=_RunOptions)

    def __init__(self) -> None:
        msg = (
            "PreparedExperiment is an opaque handle; create it with "
            "Workspace.prepare(...)"
        )
        raise TypeError(msg)

    def input(self, id: str, value: RuntimeInput) -> PreparedExperiment:  # noqa: A002
        if not id or not runtime_input_is_valid(value):
            msg = "experiment inputs require a non-empty id and closed runtime data"
            raise TypeError(msg)
        inputs = dict(self._run_options.inputs)
        inputs[id] = cast("RuntimeInput", freeze_runtime_input(value))
        return replace_handle(
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
        return replace_handle(
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
        return replace_handle(
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
        tags: Sequence[str] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> PreviewExperimentResult:
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
            execution_backend=self._execution_backend,
            execution_options=self._execution_options,
        )

    def check(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentCheckReport:
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
            execution_backend=self._execution_backend,
            execution_options=self._execution_options,
        )

    def explain(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> str:
        """Render a deterministic explanation of :meth:`check`."""

        return self.check(
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        ).explain()

    def validate(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ValidateExperimentResult:
        run_options = _validated_run_options(
            self._run_options,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return _validate_prepared(
            self._session,
            self._prepared_invocation,
            config=self._config,
            config_profile=self._config_profile,
            run_options=run_options,
            execution_backend=self._execution_backend,
            execution_options=self._execution_options,
        )

    def run(
        self,
        *,
        name: str | None = None,
        tags: Sequence[str] = (),
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
            execution_backend=self._execution_backend,
            execution_options=self._execution_options,
            run_options=run_options,
            event_sink=event_sink,
            payload_observer=payload_observer,
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Experiment:
    """Notebook-first authoring adapter for scripts and exploratory notebooks."""

    name: str
    session: Workspace | None = field(default=None, compare=False, repr=False)
    entity_inputs: Mapping[str, EntityRef | str] = field(
        default_factory=empty_frozen_mapping
    )
    module: ModuleBuilder = field(default_factory=public_authoring.module)
    scans: tuple[Scan, ...] = ()
    record_selections: tuple[ProductSelectionIntent, ...] = ()

    def __init__(self) -> None:
        msg = "Experiment is an opaque handle; create it with Workspace.experiment(...)"
        raise TypeError(msg)

    @property
    def records(self) -> tuple[RecordIntent, ...]:
        return self.module.records

    @property
    def observables(self) -> tuple[str, ...]:
        return self.module.observables

    def entity(
        self,
        input_id: str,
        entity: EntityRef | str,
        *,
        entity_kind: str | None = None,
    ) -> Experiment:
        if not input_id or not isinstance(cast("object", entity), EntityRef | str):
            msg = "experiment entity requires a non-empty input id and entity value"
            raise TypeError(msg)
        if entity_kind == "":
            msg = "experiment entity kind must be non-empty when provided"
            raise ValueError(msg)
        entity_inputs = dict(self.entity_inputs)
        entity_inputs[input_id] = cast(
            "EntityRef | str",
            freeze_runtime_input(entity),
        )
        return replace_handle(
            self,
            entity_inputs=cast(
                "Mapping[str, EntityRef | str]",
                freeze_runtime_inputs(entity_inputs),
            ),
            module=self.module.inputs(
                public_authoring.input(
                    input_id,
                    public_authoring.ScalarType(
                        public_authoring.EntityType(entity_kind=entity_kind)
                    ),
                )
            ),
        )

    def use(
        self,
        *modules: ModuleInvocation,
    ) -> Experiment:
        return replace_handle(self, module=self.module.use(*modules))

    def resource(
        self,
        id: str,  # noqa: A002
        *,
        requires: Sequence[str] = (),
        for_entities: Sequence[ValueRef] = (),
    ) -> Experiment:
        return replace_handle(
            self,
            module=self.module.resource(
                id,
                requires=requires,
                for_entities=for_entities,
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
    ) -> Experiment:
        selected = build_scan(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
        return replace_handle(
            self,
            scans=(*self.scans, selected),
        )

    def bind_field(
        self,
        resource: str,
        *,
        capability: str,
        field: str,
        value: BindingInput,
    ) -> Experiment:
        return replace_handle(
            self,
            module=self.module.bind_field(
                resource,
                capability=capability,
                field=field,
                value=value,
            ),
        )

    def compute(
        self,
        *definitions: Compute,
    ) -> Experiment:
        return replace_handle(
            self,
            module=self.module.computes(*definitions),
        )

    def state_each(
        self,
        relation: ValueRef,
        *,
        resource: StateScalarInput | None = None,
        resource_port: str | None = None,
        capability: str,
        field: str,
        value: StateScalarInput,
        route_entities: Sequence[StateRouteInput] = (),
    ) -> Experiment:
        return replace_handle(
            self,
            module=self.module.state_each(
                relation,
                resource=resource,
                resource_port=resource_port,
                field=field,
                capability=capability,
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
        axes: Sequence[RecordAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> Experiment:
        return replace_handle(
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
        *product_ids: str | ProductRef,
        record_id: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> Experiment:
        selections = tuple(
            product_selection_intent(
                record_product(
                    product_id,
                    record_id=record_id,
                    metadata=metadata,
                )
            )
            for product_id in product_ids
        )
        return replace_handle(
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
        metadata: Mapping[str, MetadataValue] | None = None,
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


class Workspace:
    """Primary vNext workspace facade for lab notebook workflows."""

    __slots__ = (
        "_config",
        "_config_profile",
        "_execution_backend",
        "_operator",
        "_reviewer",
        "_services",
        "_workspace",
    )

    _workspace: Path
    _services: WorkspaceServices
    _config: str | ConfigProfileSnapshot
    _config_profile: ConfigProfileInput | None
    _execution_backend: ExecutionBackend | None
    _reviewer: str
    _operator: str

    def __init__(self) -> None:
        msg = "Workspace is an opaque handle; create it with scopecat.open(...)"
        raise TypeError(msg)

    def __setattr__(self, name: str, _value: object) -> None:
        msg = f"cannot assign to field {name!r}"
        raise FrozenInstanceError(msg)

    def __delattr__(self, name: str) -> None:
        msg = f"cannot delete field {name!r}"
        raise FrozenInstanceError(msg)

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
    def execution_backend(self) -> ExecutionBackend | None:
        return self._execution_backend

    @property
    def reviewer(self) -> str:
        return self._reviewer

    @property
    def operator(self) -> str:
        return self._operator

    def system(
        self,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> SystemSummary:
        if isinstance(config, CandidateConfig):
            config = resolve_candidate_config_snapshot(
                config,
                services=self._services,
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
            return build_system_summary(selected_config)
        config_entry = (
            None
            if selected_config_profile is not None and selected_config == "active"
            else selected_config
        )
        resolved = resolve_config_source(
            services=self._services,
            config_profile=selected_config_profile,
            config_entry=config_entry,
        )
        return build_system_summary(resolved.config)

    def experiment(self, name: str) -> Experiment:
        return create_handle(Experiment, name=name, session=self)

    def prepare(
        self,
        experiment: (
            ExperimentInvocation | ExperimentTemplate | TemplateBuilder | Experiment
        ),
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
        execution_backend: ExecutionBackend | None = None,
        execution_options: ExecutionOptions | None = None,
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
        return create_handle(
            PreparedExperiment,
            _session=self,
            _prepared_invocation=prepared_invocation,
            _config=config,
            _config_profile=config_profile,
            _execution_backend=execution_backend,
            _execution_options=execution_options,
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
            services=self._services,
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
            services=self._services,
        )

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, manifest=manifest)
            for manifest in list_runs(services=self._services)
        )

    def get_run(self, run: RunSelector) -> RunHandle:
        details = load_run(run_id=run_handle_id(run), services=self._services)
        return RunHandle(session=self, manifest=details.manifest)

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
            services=self._services,
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
            services=self._services,
            entry_id=entry_id,
            registered_by=registered_by or self.operator,
            operator=operator or self.operator,
            note=note,
            activation_note=activation_note,
        )


def create_workspace_internal(
    *,
    workspace: Path,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot,
    config_profile: ConfigProfileInput | None,
    execution_backend: ExecutionBackend | None,
    reviewer: str,
    operator: str,
) -> Workspace:
    """Construct a composed workspace without exposing its effect bundle."""

    result = object.__new__(Workspace)
    object.__setattr__(result, "_workspace", workspace)
    object.__setattr__(result, "_services", services)
    object.__setattr__(result, "_config", config)
    object.__setattr__(result, "_config_profile", config_profile)
    object.__setattr__(result, "_execution_backend", execution_backend)
    object.__setattr__(result, "_reviewer", reviewer)
    object.__setattr__(result, "_operator", operator)
    return result


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
    execution_backend: ExecutionBackend | None,
    execution_options: ExecutionOptions | None,
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
        services=workspace_services(session),
        config=selected_config,
        config_profile=selected_config_profile,
        execution_backend=(
            session.execution_backend
            if execution_backend is None
            else execution_backend
        ),
        execution_options=execution_options,
    )


def _check_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    run_options: _RunOptions,
    execution_backend: ExecutionBackend | None,
    execution_options: ExecutionOptions | None,
) -> ExperimentCheckReport:
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
        services=workspace_services(session),
        config=selected_config,
        config_profile=selected_config_profile,
        execution_backend=(
            session.execution_backend
            if execution_backend is None
            else execution_backend
        ),
        execution_options=execution_options,
    )


def _validate_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    run_options: _RunOptions,
    execution_backend: ExecutionBackend | None,
    execution_options: ExecutionOptions | None,
) -> ValidateExperimentResult:
    try:
        selected_config, selected_config_profile = _prepared_config_selection(
            session,
            config=config,
            config_profile=config_profile,
        )
    except CheckFailed as error:
        return ValidateExperimentResult(
            problems=error.problems,
            summary=None,
            template_id=None,
            inputs={},
            config_source=None,
        )
    return validate_experiment(
        _prepared_invocation_with_run_options(
            prepared_invocation,
            options=run_options,
        ),
        services=workspace_services(session),
        config=selected_config,
        config_profile=selected_config_profile,
        execution_backend=(
            session.execution_backend
            if execution_backend is None
            else execution_backend
        ),
        execution_options=execution_options,
    )


def _run_prepared(
    session: Workspace,
    prepared_invocation: PreparedInvocation,
    *,
    config: str | ConfigProfileSnapshot | CandidateConfig | None,
    config_profile: ConfigProfileInput | None,
    execution_backend: ExecutionBackend | None,
    execution_options: ExecutionOptions | None,
    run_options: _RunOptions,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> RunHandle:
    selected_config, selected_config_profile = _prepared_config_selection(
        session,
        config=config,
        config_profile=config_profile,
    )
    selected_execution_backend = (
        session.execution_backend if execution_backend is None else execution_backend
    )
    return RunHandle(
        session=session,
        manifest=run_experiment(
            _prepared_invocation_with_run_options(
                prepared_invocation,
                options=run_options,
            ),
            services=workspace_services(session),
            config=selected_config,
            config_profile=selected_config_profile,
            execution_backend=selected_execution_backend,
            execution_options=execution_options,
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
    tags: Sequence[str],
    description: str | None,
    metadata: Mapping[str, MetadataValue] | None,
    operator: str | None,
) -> _RunOptions:
    for field_name, value in (
        ("name", name),
        ("description", description),
        ("operator", operator),
    ):
        if value is not None and not isinstance(cast("object", value), str):
            msg = f"run {field_name} must be a string or None"
            raise TypeError(msg)
    raw_tags = cast("object", tags)
    if isinstance(raw_tags, str | bytes) or not isinstance(raw_tags, Sequence):
        msg = "run tags must be a sequence of strings"
        raise TypeError(msg)
    selected_tags = tuple(cast("Sequence[object]", raw_tags))
    if not all(isinstance(tag, str) for tag in selected_tags):
        msg = "run tags must be a sequence of strings"
        raise TypeError(msg)
    return replace(
        existing,
        name=name,
        tags=cast("tuple[str, ...]", selected_tags),
        description=description,
        metadata=_merged_run_metadata(existing.metadata, metadata),
        operator=operator if operator is not None else existing.operator,
    )


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
        },
    )
    for scan in experiment.scans:
        builder = builder.scan(scan)
    builder = template_builder_with_record_selections_internal(
        builder,
        experiment.record_selections,
    )
    return builder.build()


def _workspace_module(
    experiment: Experiment,
    *,
    module_id: str,
) -> ExperimentModule:
    return experiment.module.build(
        id=module_id,
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
        "records": [
            {
                "id": record.id,
                "resource_port_id": (
                    record.resource_port_id.qualified_name
                    if record.resource_port_id is not None
                    else None
                ),
                "capability": record.capability,
                "product_key": record.product_key,
                "unit": record.unit,
                "dtype": record.dtype,
            }
            for record in experiment.module.records
        ],
        "selected_products": [
            {
                "product_id": selection.product_id.qualified_name,
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
]
