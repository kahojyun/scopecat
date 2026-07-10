from __future__ import annotations

from scopecat._compiler.program import LinkedProgram
from scopecat._relations import ParameterRelationData
from scopecat._workflows.preview import build_experiment_preview
from scopecat.diagnostics import Diagnostic
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.preview import ExperimentPreview


def preview_contract(
    experiment: LinkedProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> ExperimentPreview:
    preview, diagnostics = build_experiment_preview(
        experiment,
        parameters,
        config=config,
    )
    assert diagnostics == ()
    return preview


def preview_result(
    experiment: LinkedProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> tuple[ExperimentPreview, tuple[Diagnostic, ...]]:
    return build_experiment_preview(
        experiment,
        parameters,
        config=config,
    )
