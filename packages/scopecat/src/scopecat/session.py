"""Notebook-first workspace facade for experiment notebooks and scripts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from scopecat.analysis.online import EarlyStopDecision, decide_online_convergence
from scopecat.authoring import (
    ExperimentAuthoringContext,
    ExperimentDraft,
)
from scopecat.candidate_configs import (
    CandidateConfig,
    CandidateConfigInput,
    resolve_candidate_config,
)
from scopecat.experiments import (
    acquire,
    delete_param_rows,
    insert_param_rows,
    observe,
    set_param,
    update_param_rows,
)
from scopecat.experiments import experiment as experiment_spec
from scopecat.instruments.sdk import InstrumentProvider
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.parameter_changes import (
    ParameterChangeDecisionRecord,
    ParameterChangeReviewState,
    review_parameter_changes,
)
from scopecat.relations import col, grid, linspace, literal_rows
from scopecat.run_overview import RunOverview, build_run_overview
from scopecat.run_selectors import RunSelector
from scopecat.session_analysis import (
    Analysis,
    AnalysisContext,
    AnalysisInput,
    AnalysisOutput,
    AnalysisStep,
    PromotedAnalysisStep,
    SavedAnalysis,
)
from scopecat.session_comparison import ComparisonHandle
from scopecat.session_data import Data
from scopecat.session_run_handle import (
    RunHandle,
    run_handle_id,
)
from scopecat.session_templates import (
    TemplateBrowser,
)
from scopecat.workflows import (
    ConfigProfileInput,
    PreviewExperimentResult,
    RegisteredConfigActivation,
    ValidateExperimentResult,
    compare_runs,
    list_runs,
    load_run,
    preview_experiment,
    register_and_activate_candidate_config,
    run_experiment,
    validate_experiment,
)
from scopecat.workflows._types import ExperimentInput

QUANTITY_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+([A-Za-z][A-Za-z0-9_]*)\s*$"
)


@dataclass(frozen=True)
class SweepIntent:
    parameter_id: str
    values: tuple[object, ...] = ()
    around: object | None = None
    span: object | None = None
    points: int | None = None


@dataclass(frozen=True)
class Experiment:
    """Notebook-first experiment draft aligned with the vNext workflow."""

    name: str
    source: ExperimentInput | None = None
    subject_id: str | None = None
    sweeps: tuple[SweepIntent, ...] = ()
    observables: tuple[str, ...] = ()

    def subject(self, subject_id: str) -> Experiment:
        return replace(self, subject_id=subject_id)

    def sweep(
        self,
        parameter_id: str,
        values: Sequence[object] = (),
        *,
        around: object | None = None,
        span: object | None = None,
        points: int | None = None,
    ) -> Experiment:
        sweep = SweepIntent(
            parameter_id=parameter_id,
            values=tuple(values),
            around=around,
            span=span,
            points=points,
        )
        return replace(self, sweeps=(*self.sweeps, sweep))

    def measure(self, *observable_ids: str) -> Experiment:
        return replace(self, observables=(*self.observables, *observable_ids))

    def to_input(self) -> ExperimentInput:
        return self.source or ExperimentDraft(
            build=_build_experiment_spec,
            inputs={"experiment": self},
            template_id="scopecat.workspace.experiment",
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

    @property
    def templates(self) -> TemplateBrowser:
        return TemplateBrowser(session=self)

    def experiment(
        self,
        name: str,
        source: ExperimentInput | None = None,
    ) -> Experiment:
        return Experiment(name=name, source=source)

    def run(
        self,
        experiment: ExperimentInput | Experiment,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
        instrument_provider: InstrumentProvider | None = None,
    ) -> RunHandle:
        if isinstance(config, CandidateConfig):
            config = resolve_candidate_config(config, workspace=self.workspace).config
        return RunHandle(
            session=self,
            manifest=run_experiment(
                _experiment_input(experiment),
                workspace=self.workspace,
                config=self.config if config is None else config,
                config_profile=self._effective_config_profile(
                    config=config,
                    config_profile=config_profile,
                ),
                instrument_provider=(
                    self.instrument_provider
                    if instrument_provider is None
                    else instrument_provider
                ),
            ),
        )

    def preview(
        self,
        experiment: ExperimentInput | Experiment,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> PreviewExperimentResult:
        if isinstance(config, CandidateConfig):
            config = resolve_candidate_config(config, workspace=self.workspace).config
        return preview_experiment(
            _experiment_input(experiment),
            workspace=self.workspace,
            config=self.config if config is None else config,
            config_profile=self._effective_config_profile(
                config=config,
                config_profile=config_profile,
            ),
        )

    def validate(
        self,
        experiment: ExperimentInput | Experiment,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> ValidateExperimentResult:
        if isinstance(config, CandidateConfig):
            config = resolve_candidate_config(config, workspace=self.workspace).config
        return validate_experiment(
            _experiment_input(experiment),
            workspace=self.workspace,
            config=self.config if config is None else config,
            config_profile=self._effective_config_profile(
                config=config,
                config_profile=config_profile,
            ),
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

    def _effective_config_profile(
        self,
        *,
        config: str | ConfigProfileSnapshot | None,
        config_profile: ConfigProfileInput | None,
    ) -> ConfigProfileInput | None:
        if config is None and config_profile is None:
            return self.config_profile
        return config_profile


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


def _experiment_input(experiment: ExperimentInput | Experiment) -> ExperimentInput:
    if isinstance(experiment, Experiment):
        return experiment.to_input()
    return experiment


def _build_experiment_spec(
    context: ExperimentAuthoringContext,
    *,
    experiment: Experiment,
):
    point_sources: dict[str, object] = {}
    for sweep in experiment.sweeps:
        point_sources[sweep.parameter_id] = _sweep_source(context, sweep)
    parameter_patches = [
        set_param(sweep.parameter_id, col(sweep.parameter_id))
        for sweep in experiment.sweeps
    ]

    points = grid(**point_sources) if point_sources else literal_rows([{}])
    observations = [observe(observable_id) for observable_id in experiment.observables]
    return experiment_spec(
        id=_safe_experiment_id(experiment.name),
        kind=_safe_experiment_id(experiment.name),
        points=points,
        params=parameter_patches,
        acquire=acquire(
            "scalar",
            record="point",
            channels=([experiment.subject_id] if experiment.subject_id else []),
            observations=observations,
        ),
        assets=[],
    ).model_copy(
        update={
            "metadata": {
                "source": "workspace_experiment_builder",
                "name": experiment.name,
                "subject_id": experiment.subject_id,
            }
        }
    )


def _sweep_source(
    context: ExperimentAuthoringContext,
    sweep: SweepIntent,
) -> object:
    if sweep.values:
        return sweep.values
    if sweep.around == "active":
        if sweep.span is None:
            msg = f"sweep {sweep.parameter_id!r} around='active' requires span"
            raise ValueError(msg)
        if sweep.points is None:
            msg = f"sweep {sweep.parameter_id!r} around='active' requires points"
            raise ValueError(msg)
        center = context.require_parameter(sweep.parameter_id)
        span = _quantity(sweep.span)
        start = _offset_quantity(center, span, -0.5)
        stop = _offset_quantity(center, span, 0.5)
        return linspace(start, stop, sweep.points, unit=center.unit)
    if sweep.around is not None:
        msg = f"unsupported sweep center for {sweep.parameter_id!r}: {sweep.around!r}"
        raise ValueError(msg)
    msg = f"sweep {sweep.parameter_id!r} requires explicit values or around='active'"
    raise ValueError(msg)


def _quantity(value: object) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if isinstance(value, str):
        match = QUANTITY_RE.fullmatch(value)
        if match is not None:
            return Quantity(value=float(match.group(1)), unit=match.group(2))
    msg = f"expected quantity value like '100 MHz', got {value!r}"
    raise TypeError(msg)


def _offset_quantity(center: Quantity, span: Quantity, scale: float) -> Quantity:
    if center.unit == span.unit:
        return Quantity(value=center.value + span.value * scale, unit=center.unit)
    from scopecat.units import compatible_units, from_base_value, to_base_value

    if not compatible_units(center.unit, span.unit):
        msg = f"incompatible sweep units: {center.unit!r} and {span.unit!r}"
        raise ValueError(msg)
    center_base = to_base_value(center.value, center.unit)
    span_base = to_base_value(span.value, span.unit)
    if center_base is None or span_base is None:
        msg = (
            f"sweep units are not linearly convertible: {center.unit!r}, {span.unit!r}"
        )
        raise ValueError(msg)
    converted = from_base_value(center_base + span_base * scale, center.unit)
    if converted is None:
        msg = f"sweep unit is not linearly convertible: {center.unit!r}"
        raise ValueError(msg)
    return Quantity(value=converted, unit=center.unit)


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
    "PromotedAnalysisStep",
    "Quantity",
    "RunHandle",
    "SavedAnalysis",
    "SweepIntent",
    "TemplateBrowser",
    "Workspace",
    "decide_online_convergence",
    "delete_param_rows",
    "insert_param_rows",
    "open",
    "set_param",
    "update_param_rows",
]
