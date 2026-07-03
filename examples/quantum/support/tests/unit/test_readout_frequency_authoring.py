from __future__ import annotations

from demo_lab_readout_frequency_testkit import config_profile_snapshot
from demo_lab_test_paths import READOUT_FREQUENCY_FIXTURE_DIR
from scopecat.authoring import around, resolve_experiment
from scopecat.experiments import ExperimentSpec, plan_experiment
from scopecat.models.parameter import Quantity

from quantum_lab_demo.readout import (
    frequency_calibration,
)


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
