from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from scopecat.authoring import ExperimentInvocation
from scopecat.config.profiles import load_config_profile
from scopecat.execution.observation import RuntimeEvent, RuntimeTransitionEvent
from scopecat.records.config import ConfigProfileSnapshot

from quantum_lab_demo.experiments import (
    BACKEND_BATCH_TEMPLATE,
    CZ_CHEVRON_TEMPLATE,
    CZ_RB_TEMPLATE,
    QND_REPEATED_MEASUREMENT_TEMPLATE,
    RABI_TEMPLATE,
    READOUT_TEMPLATE,
    TOY_SURFACE_CODE_ROUND_TEMPLATE,
)
from quantum_lab_demo.experiments.points import (
    CLIFFORD_COUNT,
    COUPLER_AMPLITUDE,
    COUPLER_DURATION,
)
from quantum_lab_demo.experiments.readout_responses import settings_from_config
from quantum_lab_demo.lab import quantum_lab
from quantum_lab_demo.reference_experiments.single_qubit_rb import (
    CLIFFORD_LENGTH,
    RB_SEED,
    single_qubit_rb_template,
)

from .demo_lab_test_paths import (
    EXPERIMENT_FIXTURE_DIR,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
)

_CZ_CHEVRON_SCOPE = "cz_chevron"
_BACKEND_BATCH_SCOPE = "batch"


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
            RABI_TEMPLATE.bind(qubit="q0"),
            ("drive_length",),
            5,
        ),
        (
            READOUT_TEMPLATE.bind(qubit="q0"),
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
        (
            CZ_RB_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                seed=17,
            ).scan(CLIFFORD_COUNT, [2, 4]),
            ("clifford_count",),
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


def test_cz_chevron_emits_scoped_compute_lifecycle_summaries(
    tmp_path: Path,
) -> None:
    events: list[RuntimeEvent] = []

    run = (
        _lab(tmp_path)
        .prepare(
            CZ_CHEVRON_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
            )
            .scan(COUPLER_DURATION, [24], unit="ns")
            .scan(COUPLER_AMPLITUDE, [0.18], unit="arb")
        )
        .run(
            event_sink=events.append,
        )
    )

    compute_events = [
        event
        for event in events
        if isinstance(event, RuntimeTransitionEvent)
        and event.stage == "compute"
        and event.state == "completed"
    ]
    drive_event = next(
        event
        for event in compute_events
        if event.metrics.get("semantic_operation_id")
        == f"{_CZ_CHEVRON_SCOPE}/render-cz-chevron-drive-waveforms"
    )
    program_event = next(
        event
        for event in compute_events
        if event.metrics.get("semantic_operation_id")
        == f"{_CZ_CHEVRON_SCOPE}/build-cz-chevron-program"
    )

    assert run.manifest.status == "completed"
    for event in (program_event, drive_event):
        semantic_operation_id = cast("str", event.metrics["semantic_operation_id"])
        implementation_id = cast("str", event.metrics["implementation_id"])
        payload_id = cast("str", event.metrics["payload_id"])
        assert implementation_id.startswith("python:")
        assert implementation_id.endswith(f":{semantic_operation_id}")
        assert payload_id.startswith(f"{semantic_operation_id}/outputs/result.payload.")
        assert event.operation_id.endswith(f".compute.{semantic_operation_id}")


@pytest.mark.parametrize(
    ("invocation", "observable_id", "shape"),
    [
        (
            QND_REPEATED_MEASUREMENT_TEMPLATE.bind(
                qubit="q0",
                rounds=2,
                shots=3,
            ),
            "qnd_iq",
            [1, 3, 2],
        ),
        (
            TOY_SURFACE_CODE_ROUND_TEMPLATE.bind(rounds=2, shots=3),
            "stabilizer_iq",
            [1, 3, 2, 4],
        ),
        (
            BACKEND_BATCH_TEMPLATE.bind(
                logical_points=4,
                seed=5,
            ),
            "backend_probabilities",
            [1, 4],
        ),
    ],
)
def test_array_record_cases_run_provider_python_api(
    tmp_path: Path,
    invocation: ExperimentInvocation,
    observable_id: str,
    shape: list[int],
) -> None:
    events: list[RuntimeEvent] = []

    run = _lab(tmp_path).prepare(invocation).run(event_sink=events.append)
    measurements = run.data().measurements()
    observable = next(
        variable
        for variable in measurements.dataset.dataset_schema.variables
        if variable.id == observable_id
    )

    assert run.manifest.status == "completed"
    assert len(measurements.dataset.records) == 1
    assert observable.shape == shape
    if observable_id == "backend_probabilities":
        batch_event = next(
            event
            for event in events
            if isinstance(event, RuntimeTransitionEvent)
            and event.stage == "compute"
            and event.state == "completed"
            and event.metrics.get("semantic_operation_id")
            == f"{_BACKEND_BATCH_SCOPE}/build-backend-batch-job"
        )
        payload_id = cast("str", batch_event.metrics["payload_id"])
        assert payload_id.startswith(
            f"{_BACKEND_BATCH_SCOPE}/build-backend-batch-job/outputs/result.payload."
        )


def _lab(tmp_path: Path):
    return quantum_lab(
        workspace=tmp_path,
        config_profile=load_config(),
        virtual_lab_profile=EXPERIMENT_VIRTUAL_LAB_PROFILE,
    )
