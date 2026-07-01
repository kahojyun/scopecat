from __future__ import annotations

from demo_lab_readout_frequency_testkit import config_profile_snapshot
from demo_lab_test_paths import READOUT_FREQUENCY_FIXTURE_DIR
from scopecat.authoring import around, resolve_experiment
from scopecat.experiments import ExperimentSpec, plan_experiment
from scopecat.models.parameter import Quantity
from scopecat.workflows import AnalysisStepCatalogContext

from quantum_lab_demo.readout import (
    READOUT_FREQUENCY_ANALYSIS_STEP,
    ReadoutFrequencyAnalysisStep,
    frequency_calibration,
)
from quantum_lab_demo.readout.analysis_catalog import (
    ReadoutAnalysisCatalog,
)


def test_readout_frequency_catalog_resolves_expected_analysis_step() -> None:
    catalog = ReadoutAnalysisCatalog()
    description = catalog.describe()

    analysis = catalog.analysis_step(
        AnalysisStepCatalogContext(step_id=READOUT_FREQUENCY_ANALYSIS_STEP)
    )
    unsupported = catalog.analysis_step(
        AnalysisStepCatalogContext(step_id="missing-analysis")
    )

    assert description.catalog_id == "quantum_lab_demo.readout_analysis"
    assert [step.step_id for step in description.steps] == [
        "readout.frequency.analysis",
        "readout.iq_quality.analysis",
    ]
    assert description.steps[0].output_artifact_kinds == ("analysis",)
    assert description.steps[0].proposal_kinds == ("readout_frequency",)
    assert isinstance(analysis.step, ReadoutFrequencyAnalysisStep)
    assert unsupported.diagnostics[0].code == "readout_analysis_step_unsupported"


def test_readout_frequency_template_resolves_fixture_equivalent_plan() -> None:
    config = config_profile_snapshot()
    draft = frequency_calibration(
        qubit="q0",
        sweep=around(
            "readout_frequency",
            span=Quantity(value=100.0, unit="MHz"),
            points=101,
        ),
    )
    resolved = resolve_experiment(
        draft,
        workspace=READOUT_FREQUENCY_FIXTURE_DIR,
        config_profile=config,
    )
    assert config.parameter_build is not None
    resolved_experiment = resolved.experiment
    assert isinstance(resolved_experiment, ExperimentSpec)
    generated_plan = plan_experiment(resolved_experiment, config.parameter_build)

    assert resolved.template_id == ("quantum_lab_demo.readout.frequency_calibration")
    assert resolved_experiment.kind == "readout_frequency_calibration"
    assert generated_plan.point_coordinate_ids == [
        "readout_frequency",
        "lo_frequency",
    ]
    assert len(generated_plan.points) == 101
    assert generated_plan.desired_state
    assert generated_plan.acquisition.kind == "iq"
    assert generated_plan.expected_dataset_schema is not None
    assert "readout_frequency" in (
        generated_plan.expected_dataset_schema.primary_coordinates
    )
    assert generated_plan.expected_dataset_schema.primary_observables == [
        "raw_i",
        "raw_q",
    ]
