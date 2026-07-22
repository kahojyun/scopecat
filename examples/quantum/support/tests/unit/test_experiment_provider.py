from __future__ import annotations

from pathlib import Path

import pytest
from scopecat.authoring import ExperimentInvocation
from scopecat.config.profiles import load_config_profile
from scopecat.records.config import ConfigProfileSnapshot

from quantum_lab_demo.lab import quantum_lab
from quantum_lab_demo.virtual_lab.responses.readout_frequency import (
    settings_from_config,
)
from quantum_lab_demo.workflows.fixed_patch_readout import fixed_patch_readout_template
from quantum_lab_demo.workflows.qnd import qnd_repeated_measurement_template
from quantum_lab_demo.workflows.readout_frequency import readout_frequency_template
from quantum_lab_demo.workflows.single_qubit_rb import (
    CLIFFORD_LENGTH,
    RB_SEED,
    single_qubit_rb_template,
)

from .demo_lab_test_paths import (
    EXPERIMENT_FIXTURE_DIR,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
)


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")


def test_readout_settings_come_from_the_typed_qubit_table() -> None:
    q0 = settings_from_config(load_config(), qubit="q0")
    q1 = settings_from_config(load_config(), qubit="q1")

    assert q0.readout_frequency_ghz == 6.5
    assert q0.readout_power_dbm == -20.0
    assert q1.readout_frequency_ghz == 6.7
    assert q1.readout_power_dbm == -21.0


@pytest.mark.parametrize(
    ("invocation", "expected_coordinate_ids", "expected_measurements"),
    [
        (
            readout_frequency_template.bind(qubit="q0"),
            ("readout_frequency",),
            5,
        ),
        (
            single_qubit_rb_template.bind()
            .scan(CLIFFORD_LENGTH, [4, 8])
            .scan(RB_SEED, [11]),
            ("clifford_length", "rb_seed"),
            2,
        ),
    ],
)
def test_experiment_system_run_provider_python_api(
    tmp_path: Path,
    invocation: ExperimentInvocation,
    expected_coordinate_ids: tuple[str, ...],
    expected_measurements: int,
) -> None:
    run = _lab(tmp_path).prepare(invocation).run()
    measurements = run.data().measurements()

    assert run.manifest.status == "completed"
    assert measurements.dataset.dataset_schema.primary_coordinates == list(
        expected_coordinate_ids
    )
    assert len(measurements.dataset.records) == expected_measurements


@pytest.mark.parametrize(
    ("invocation", "observable_id", "shape"),
    [
        (
            qnd_repeated_measurement_template.bind(
                qubit="q0",
                rounds=2,
                shots=3,
            ),
            "qnd_iq",
            [1, 3, 2],
        ),
        (
            fixed_patch_readout_template.bind(rounds=2, shots=3),
            "patch_iq",
            [1, 3, 2, 4],
        ),
    ],
)
def test_array_record_cases_run_provider_python_api(
    tmp_path: Path,
    invocation: ExperimentInvocation,
    observable_id: str,
    shape: list[int],
) -> None:
    run = _lab(tmp_path).prepare(invocation).run()
    measurements = run.data().measurements()
    observable = next(
        variable
        for variable in measurements.dataset.dataset_schema.variables
        if variable.id == observable_id
    )

    assert run.manifest.status == "completed"
    assert len(measurements.dataset.records) == 1
    assert observable.shape == shape


def _lab(tmp_path: Path):
    return quantum_lab(
        workspace=tmp_path,
        config_profile=load_config(),
        virtual_lab_profile=EXPERIMENT_VIRTUAL_LAB_PROFILE,
    )
