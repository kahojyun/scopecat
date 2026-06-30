"""Analysis catalog and internal step execution workflow use cases."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from scopecat.errors import ValidationFailed
from scopecat.evaluation import EvaluationStep, execute_evaluation_step
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.processing import ProcessingStep, execute_processing_step
from scopecat.workflows._diagnostics import diagnostic as _diagnostic
from scopecat.workflows._types import (
    AnalysisCatalog,
    AnalysisCatalogDescription,
    AnalysisStepCatalogContext,
    CalibrationRoutine,
    CalibrationRoutineDescription,
    EvaluateRunResult,
    ProcessRunResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from scopecat.session_analysis import AnalysisStep


def describe_analysis_catalog(
    catalog: AnalysisCatalog,
) -> AnalysisCatalogDescription:
    return catalog.describe()


def resolve_analysis_step(
    *,
    catalog: AnalysisCatalog,
    step_id: str,
    options: Mapping[str, object] | None = None,
) -> AnalysisStep:
    catalog_result = catalog.analysis_step(
        AnalysisStepCatalogContext(step_id=step_id, options=options or {})
    )
    diagnostics = list(catalog_result.diagnostics)
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    if catalog_result.step is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "analysis_catalog_missing_step",
                    "analysis catalog returned no step",
                    "catalog",
                )
            ]
        )
    return catalog_result.step


def describe_calibration_routine(
    routine: CalibrationRoutine,
) -> CalibrationRoutineDescription:
    return CalibrationRoutineDescription(
        routine_id=routine.id,
        run_executor_id=routine.run_executor.id,
        analysis_steps=tuple(step.id for step in routine.analysis_steps),
        reviews_candidate=routine.review_candidate is not None,
        label=routine.label,
        description=routine.description,
        metadata=dict(routine.metadata),
    )


def process_run[TResult](
    *,
    run_id: str,
    workspace: str | Path,
    step: ProcessingStep[TResult],
) -> ProcessRunResult[TResult]:
    job, result = execute_processing_step(
        run_id=run_id,
        workspace=workspace,
        step=step,
    )
    return ProcessRunResult(job=job, result=result)


def evaluate_run[TResult, TProposal](
    *,
    run_id: str,
    workspace: str | Path,
    step: EvaluationStep[TResult, TProposal],
) -> EvaluateRunResult[TResult, TProposal]:
    job, result, proposals = execute_evaluation_step(
        run_id=run_id,
        workspace=workspace,
        step=step,
    )
    return EvaluateRunResult(job=job, result=result, proposals=proposals)
