from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import scopecat as sc
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.workflows._types import CalibrationRoutine
from scopecat.workflows.routines import run_calibration_routine
from scopecat.workflows.runs import run_mode_executor
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_config, load_experiment


def test_calibration_routine_runs_ordered_analysis_steps(
    tmp_path: Path,
) -> None:
    order: list[str] = []
    routine = CalibrationRoutine(
        id="ordered-demo",
        experiment=load_experiment(),
        run_executor=run_mode_executor(
            "native_simulate", native_instrument_provider=TestSignalInstrumentProvider()
        ),
        analysis_steps=(
            OrderedAnalysisStep("analysis-a", order),
            OrderedAnalysisStep("analysis-b", order),
        ),
    )

    result = run_calibration_routine(
        routine=routine,
        config=load_config(),
        workspace=tmp_path,
    )

    assert order == ["analysis-a", "analysis-b"]
    assert [analysis.title for analysis in result.analyses] == [
        "analysis-a",
        "analysis-b",
    ]


def test_calibration_routine_failing_analysis_step_stops_later_steps(
    tmp_path: Path,
) -> None:
    order: list[str] = []
    routine = CalibrationRoutine(
        id="failing-demo",
        experiment=load_experiment(),
        run_executor=run_mode_executor(
            "native_simulate", native_instrument_provider=TestSignalInstrumentProvider()
        ),
        analysis_steps=(
            OrderedAnalysisStep("analysis-before-failure", order),
            FailingAnalysisStep(order),
            OrderedAnalysisStep("analysis-after-failure", order),
        ),
    )

    with pytest.raises(ValidationFailed) as error:
        run_calibration_routine(
            routine=routine,
            config=load_config(),
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "routine_analysis_failed"
    assert order == ["analysis-before-failure", "failing-analysis"]
    run_dirs = sorted((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1


@dataclass
class OrderedAnalysisStep:
    id: str
    order: list[str]

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        self.order.append(self.id)
        return context.result(self.id).note(self.id)


@dataclass
class FailingAnalysisStep:
    order: list[str]
    id: str = "failing-analysis"

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        del context
        self.order.append(self.id)
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="routine_analysis_failed",
                    message="routine analysis failed",
                    path="step",
                )
            ]
        )
