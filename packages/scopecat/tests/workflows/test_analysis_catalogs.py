from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.workflows import (
    AnalysisCatalogDescription,
    AnalysisStepCatalogContext,
    AnalysisStepCatalogResult,
    AnalysisStepDescription,
    ProviderOptionDescription,
    describe_analysis_catalog,
    resolve_analysis_step,
)
from scopecat.workflows._types import CalibrationRoutine, CandidateReviewPolicy
from scopecat.workflows.runs import run_mode_executor
from scopecat.workflows.steps import describe_calibration_routine
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.signal_testkit import (
    BEST_SIGNAL_ANALYSIS_STEP,
    TestSignalAnalysisCatalog,
    TestSignalAnalysisStep,
)
from tests.support.workflow_fixtures import load_config, load_experiment


def test_analysis_catalog_descriptor_models_round_trip_defaults() -> None:
    option = ProviderOptionDescription(id="input", dtype="string | None")
    step = AnalysisStepDescription(step_id=BEST_SIGNAL_ANALYSIS_STEP)
    catalog = AnalysisCatalogDescription(
        catalog_id="test.catalog",
        steps=(step,),
    )

    assert option.required is False
    assert option.default is None
    assert step.options == ()
    assert step.guess_kinds == ()
    assert catalog.steps == (step,)


def test_analysis_catalog_describes_supported_steps() -> None:
    description = TestSignalAnalysisCatalog().describe()

    assert describe_analysis_catalog(TestSignalAnalysisCatalog()) == description
    assert description.catalog_id == "tests.signal_analysis"
    assert [step.step_id for step in description.steps] == [BEST_SIGNAL_ANALYSIS_STEP]
    assert description.steps[0].options[0].id == "input"
    assert description.steps[0].options[0].dtype == "string | None"
    assert description.steps[0].input_artifact_kinds == ("measurement_dataset",)
    assert description.steps[0].guess_kinds == ("drive_frequency",)


def test_describe_analysis_catalog_passes_through_custom_catalog() -> None:
    custom_description = AnalysisCatalogDescription(
        catalog_id="test.custom_analysis",
        steps=(
            AnalysisStepDescription(
                step_id="custom-analysis",
                metadata={"category": "test"},
            ),
        ),
    )

    class CustomCatalog:
        catalog_id = "test.custom_analysis"

        def describe(self) -> AnalysisCatalogDescription:
            return custom_description

        def analysis_step(
            self, context: AnalysisStepCatalogContext
        ) -> AnalysisStepCatalogResult:
            del context
            return AnalysisStepCatalogResult(
                diagnostics=(
                    Diagnostic(
                        severity="error",
                        code="custom_not_implemented",
                        message="custom not implemented",
                        path="step_id",
                    ),
                )
            )

    assert describe_analysis_catalog(CustomCatalog()) == custom_description


def test_test_signal_provider_describes_static_capabilities() -> None:
    description = TestSignalInstrumentProvider(instrument_id="source-a").describe()

    assert description.provider_id == "tests.signal_instrument_provider"
    assert description.provided_instrument_ids == ("source-a",)
    assert description.options[0].id == "instrument_id"
    assert description.options[0].default == "source-a"
    assert description.capabilities == ("set_frequency", "scalar_signal")
    assert description.metadata["mode"] == "test_offline"


def test_describe_calibration_routine_returns_ordered_structure() -> None:
    routine = CalibrationRoutine(
        id="demo-best-signal-descriptor",
        experiment=load_experiment(),
        run_executor=run_mode_executor(
            "native_simulate", native_instrument_provider=TestSignalInstrumentProvider()
        ),
        analysis_steps=(TestSignalAnalysisStep(),),
        review_candidate=CandidateReviewPolicy(
            reviewer="operator",
        ),
        label="Demo best signal",
        description="Demo calibration routine",
        metadata={"category": "demo"},
    )

    description = describe_calibration_routine(routine)

    assert description.routine_id == "demo-best-signal-descriptor"
    assert description.run_executor_id == "native_simulate"
    assert description.analysis_steps == ("best-signal-analysis",)
    assert description.reviews_candidate is True
    assert description.label == "Demo best signal"
    assert description.description == "Demo calibration routine"
    assert description.metadata == {"category": "demo"}


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
