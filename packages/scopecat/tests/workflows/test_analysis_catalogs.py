from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.errors import ValidationFailed
from scopecat.workflows import (
    AnalysisStepCatalogContext,
    resolve_analysis_step,
)
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.signal_testkit import (
    BEST_SIGNAL_ANALYSIS_STEP,
    TestSignalAnalysisCatalog,
    TestSignalAnalysisStep,
)
from tests.support.workflow_fixtures import load_config, load_experiment


def test_analysis_catalog_resolves_supported_step() -> None:
    catalog = TestSignalAnalysisCatalog()

    result = catalog.analysis_step(
        AnalysisStepCatalogContext(
            step_id=BEST_SIGNAL_ANALYSIS_STEP,
            options={"input": "raw-measurements"},
        )
    )

    assert catalog.catalog_id == "tests.signal_analysis"
    assert isinstance(result.step, TestSignalAnalysisStep)
    assert result.step.selector == "raw-measurements"


def test_analysis_catalog_rejects_unsupported_and_invalid_options() -> None:
    catalog = TestSignalAnalysisCatalog()

    unsupported = catalog.analysis_step(
        AnalysisStepCatalogContext(step_id="missing-analysis")
    )
    invalid_option = catalog.analysis_step(
        AnalysisStepCatalogContext(
            step_id=BEST_SIGNAL_ANALYSIS_STEP,
            options={"input": 123},
        )
    )

    assert unsupported.diagnostics[0].code == "unsupported_analysis_step"
    assert invalid_option.diagnostics[0].code == "invalid_analysis_catalog_option"


def test_resolve_analysis_step_raises_for_catalog_diagnostics() -> None:
    with pytest.raises(ValidationFailed) as error:
        resolve_analysis_step(
            catalog=TestSignalAnalysisCatalog(),
            step_id="missing-analysis",
        )

    assert error.value.diagnostics[0].code == "unsupported_analysis_step"


def test_run_handle_analyzes_catalog_step(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config=load_config(),
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = lab.experiment(
        "signal scan",
        source=load_experiment(),
    )
    run = lab.run(experiment)
    step = resolve_analysis_step(
        catalog=TestSignalAnalysisCatalog(),
        step_id=BEST_SIGNAL_ANALYSIS_STEP,
        options={"input": "raw-measurements"},
    )

    analysis = run.analyze(step)

    assert analysis.title == "best signal analysis"
    assert analysis.parameter_guesses[0].parameter_id == "drive_frequency"
    assert [output.title for output in analysis.outputs] == [
        "raw measurements",
        "signal summary",
        "drive_frequency",
    ]
