from __future__ import annotations

from pathlib import Path

import pytest
from demo_lab_test_paths import (
    SAMPLE_TEMPLATES_FIXTURE_DIR,
    SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE,
)
from scopecat.authoring import ExperimentDraft, resolve_experiment
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.workflows import read_run_measurement_dataset, run_experiment

from quantum_lab_demo.sample import (
    cz_rb,
    rabi,
    readout_frequency,
    sqg_rb,
)
from quantum_lab_demo.virtual_lab.provider import SampleVirtualProvider


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(SAMPLE_TEMPLATES_FIXTURE_DIR / "config-profile.json")


@pytest.mark.parametrize(
    ("draft", "expected_coordinate_id", "expected_measurements"),
    [
        (
            rabi(qubit="q0"),
            "drive_length",
            5,
        ),
        (
            readout_frequency(qubit="q0"),
            "readout_frequency",
            5,
        ),
        (
            sqg_rb(qubit="q0", lengths=[4, 8], seed=11),
            "clifford_count",
            2,
        ),
        (
            cz_rb(control_qubit="q0", partner_qubit="q1", lengths=[2, 4], seed=17),
            "clifford_count",
            2,
        ),
    ],
)
def test_sample_templates_run_provider_python_api(
    tmp_path: Path,
    draft: ExperimentDraft,
    expected_coordinate_id: str,
    expected_measurements: int,
) -> None:
    manifest = run_experiment(
        draft,
        config_profile=load_config(),
        workspace=tmp_path,
        instrument_provider=SampleVirtualProvider(
            profile=SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE
        ),
    )
    measurements = read_run_measurement_dataset(
        run_id=manifest.run_id,
        workspace=tmp_path,
    )

    assert manifest.status == "completed"
    assert measurements.dataset.dataset_schema.primary_coordinates == [
        expected_coordinate_id
    ]
    assert len(measurements.dataset.records) == expected_measurements


def test_sample_rejects_invalid_asset_kind(
    tmp_path: Path,
) -> None:
    resolved = resolve_experiment(
        rabi(qubit="q0"),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    assert isinstance(resolved.experiment, ExperimentSpec)
    experiment = resolved.experiment.model_copy(
        update={
            "assets": [
                resolved.experiment.assets[0].model_copy(
                    update={"kind": "gate_sequence"}
                )
            ]
        }
    )

    with pytest.raises(ValidationFailed) as error:
        run_experiment(
            experiment,
            config=load_config(),
            workspace=tmp_path,
            instrument_provider=SampleVirtualProvider(
                profile=SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE
            ),
        )

    assert error.value.diagnostics[0].code == "managed_instrument_asset_kind_mismatch"
