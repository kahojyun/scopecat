from __future__ import annotations

from scopecat._workflows.preview import build_experiment_preview
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.parameters import ParameterDerivationSet
from scopecat.preview import ExperimentPreview


def preview_contract(
    experiment: ExperimentSpec,
    parameter_view: ParameterViewSnapshot,
    *,
    config: ConfigProfileSnapshot | None = None,
    derivations: ParameterDerivationSet | None = None,
) -> ExperimentPreview:
    preview, diagnostics = build_experiment_preview(
        experiment,
        parameter_view,
        config=config,
        derivations=derivations,
    )
    assert diagnostics == ()
    return preview


def preview_result(
    experiment: ExperimentSpec,
    parameter_view: ParameterViewSnapshot,
    *,
    config: ConfigProfileSnapshot | None = None,
    derivations: ParameterDerivationSet | None = None,
) -> tuple[ExperimentPreview, tuple[Diagnostic, ...]]:
    return build_experiment_preview(
        experiment,
        parameter_view,
        config=config,
        derivations=derivations,
    )
