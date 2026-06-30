"""Notebook-first workspace facade for experiment notebooks and scripts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from scopecat.authoring import (
    ExperimentAuthoringContext,
    ExperimentDraft,
    ResolvedExperiment,
)
from scopecat.client import Client, RunRef
from scopecat.experiments import acquire, observe, set_param
from scopecat.experiments import experiment as experiment_spec
from scopecat.instruments.sdk import NativeInstrumentProvider
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.relations import col, grid, linspace, literal_rows
from scopecat.reporting import render_run_overview
from scopecat.session_analysis import (
    Analysis,
    AnalysisContext,
    AnalysisExternalRef,
    AnalysisOutput,
    AnalysisStep,
    PromotedAnalysisStep,
    SavedAnalysis,
)
from scopecat.session_candidate_config import (
    CandidateConfig,
    CandidateConfigReview,
    ParameterGuess,
)
from scopecat.session_comparison import ComparisonHandle
from scopecat.session_data import Data
from scopecat.session_overview import OverviewHandle
from scopecat.session_run_handle import (
    RunHandle,
    run_handle_id,
)
from scopecat.session_templates import (
    TemplateBrowser,
)
from scopecat.workflows import (
    ConfigProfileInput,
    RunMode,
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
class _WorkspaceSession:
    """Shared implementation for one concrete workspace and execution context."""

    client: Client
    reviewer: str = "operator"
    operator: str = "operator"

    @classmethod
    def from_profile(
        cls,
        config_profile: ConfigProfileInput,
        *,
        workspace: str | Path,
        mode: RunMode = "dry",
        native_instrument_provider: NativeInstrumentProvider | None = None,
        reviewer: str = "operator",
        operator: str = "operator",
    ) -> _WorkspaceSession:
        return cls(
            client=Client.from_profile(
                config_profile,
                workspace=workspace,
                mode=mode,
                native_instrument_provider=native_instrument_provider,
            ),
            reviewer=reviewer,
            operator=operator,
        )

    @property
    def workspace(self) -> Path:
        return Path(self.client.workspace)

    @property
    def templates(self) -> TemplateBrowser:
        return TemplateBrowser(session=self)

    def run(
        self,
        experiment: ExperimentInput,
        *,
        config: str | ConfigProfileSnapshot | None = None,
        config_profile: ConfigProfileInput | None = None,
        mode: RunMode | None = None,
        native_instrument_provider: NativeInstrumentProvider | None = None,
    ) -> RunHandle:
        if config is not None:
            override_client = Client(
                workspace=self.workspace,
                config=config,
                config_profile=config_profile,
                mode=mode or self.client.mode,
                native_instrument_provider=(
                    native_instrument_provider
                    if native_instrument_provider is not None
                    else self.client.native_instrument_provider
                ),
            )
            return RunHandle(
                session=self,
                result=override_client.run(experiment),
            )
        return RunHandle(
            session=self,
            result=self.client.run(
                experiment,
                config=config,
                config_profile=config_profile,
                mode=mode,
                native_instrument_provider=native_instrument_provider,
            ),
        )

    def preview(
        self,
        experiment: ExperimentDraft,
        *,
        config: str | ConfigProfileSnapshot | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> ResolvedExperiment:
        if config is not None:
            return Client(
                workspace=self.workspace,
                config=config,
                config_profile=config_profile,
                mode=self.client.mode,
                native_instrument_provider=self.client.native_instrument_provider,
            ).resolve(experiment)
        return self.client.resolve(
            experiment,
            config=config,
            config_profile=config_profile,
        )

    def compare(
        self,
        baseline: RunHandle | RunRef,
        candidate: RunHandle | RunRef,
        *,
        observable: str | None = None,
    ) -> ComparisonHandle:
        baseline_id = run_handle_id(baseline)
        result = self.client.compare_runs(
            baseline_id,
            run_handle_id(candidate),
            observable_id=observable,
        )
        return ComparisonHandle(
            session=self,
            baseline_run_id=baseline_id,
            workflow=result,
        )

    def overview(self, run: RunHandle | RunRef) -> OverviewHandle:
        overview = self.client.overview(run_handle_id(run))
        return OverviewHandle(
            session=self,
            overview=overview,
            markdown=render_run_overview(overview),
        )

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, manifest=view.manifest)
            for view in self.client.runs()
        )

    def get_run(self, run: RunRef) -> RunHandle:
        details = self.client.run_details(run)
        return RunHandle(session=self, manifest=details.manifest)


@dataclass(frozen=True, kw_only=True)
class Workspace(_WorkspaceSession):
    """Primary vNext workspace facade for lab notebook workflows."""

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
        config: str
        | ConfigProfileSnapshot
        | CandidateConfig
        | CandidateConfigReview
        | None = None,
        config_profile: ConfigProfileInput | None = None,
        mode: RunMode | None = None,
        native_instrument_provider: NativeInstrumentProvider | None = None,
    ) -> RunHandle:
        if isinstance(config, CandidateConfig):
            config = self.review(config)
        if isinstance(config, CandidateConfigReview):
            config = config.config
        return super().run(
            _experiment_input(experiment),
            config=config,
            config_profile=config_profile,
            mode=mode,
            native_instrument_provider=native_instrument_provider,
        )

    def review(
        self,
        candidate: CandidateConfig,
        *,
        reviewer: str | None = None,
        note: str = "",
    ) -> CandidateConfigReview:
        return candidate.review(
            workspace=self.workspace,
            reviewer=reviewer or self.reviewer,
            note=note,
        )

    def preview(
        self,
        experiment: ExperimentDraft | Experiment,
        *,
        config: str | ConfigProfileSnapshot | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> ResolvedExperiment:
        return super().preview(
            _experiment_draft(experiment),
            config=config,
            config_profile=config_profile,
        )


def open(  # noqa: A001
    workspace: str | Path,
    *,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    mode: RunMode = "dry",
    native_instrument_provider: NativeInstrumentProvider | None = None,
    reviewer: str = "operator",
    operator: str = "operator",
) -> Workspace:
    return Workspace(
        client=Client(
            workspace=workspace,
            config=config,
            config_profile=config_profile,
            mode=mode,
            native_instrument_provider=native_instrument_provider,
        ),
        reviewer=reviewer,
        operator=operator,
    )


def _experiment_input(experiment: ExperimentInput | Experiment) -> ExperimentInput:
    if isinstance(experiment, Experiment):
        return experiment.to_input()
    return experiment


def _experiment_draft(experiment: ExperimentDraft | Experiment) -> ExperimentDraft:
    if isinstance(experiment, Experiment):
        source = experiment.to_input()
        if isinstance(source, ExperimentDraft):
            return source
        msg = "workspace preview requires an ExperimentDraft source"
        raise TypeError(msg)
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
    "AnalysisExternalRef",
    "AnalysisOutput",
    "AnalysisStep",
    "CandidateConfig",
    "CandidateConfigReview",
    "ComparisonHandle",
    "Data",
    "Experiment",
    "OverviewHandle",
    "ParameterGuess",
    "PromotedAnalysisStep",
    "RunHandle",
    "SavedAnalysis",
    "SweepIntent",
    "TemplateBrowser",
    "Workspace",
    "open",
]
