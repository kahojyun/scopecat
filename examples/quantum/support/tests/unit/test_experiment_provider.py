from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from demo_lab_test_paths import (
    EXPERIMENT_FIXTURE_DIR,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
)
from scopecat.authoring import (
    ExperimentInvocation,
    PayloadType,
    ScalarType,
)
from scopecat.compiler.linking.linked import link_program
from scopecat.config.profiles import load_config_profile
from scopecat.execution.observation import RuntimeEvent, RuntimeTransitionEvent
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.config import ConfigProfileSnapshot

from quantum_lab_demo.experiments import (
    BACKEND_BATCH_TEMPLATE,
    CZ_CHEVRON_TEMPLATE,
    CZ_RB_TEMPLATE,
    QND_REPEATED_MEASUREMENT_TEMPLATE,
    RABI_TEMPLATE,
    READOUT_TEMPLATE,
    SQG_RB_TEMPLATE,
    TOY_SURFACE_CODE_ROUND_TEMPLATE,
)
from quantum_lab_demo.experiments.points import (
    CLIFFORD_COUNT,
    COUPLER_AMPLITUDE,
    COUPLER_DURATION,
)
from quantum_lab_demo.experiments.readout_responses import _settings_from_config
from quantum_lab_demo.lab import quantum_lab

_CZ_CHEVRON_SCOPE = "cz_chevron"
_BACKEND_BATCH_SCOPE = "batch"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")


def test_readout_settings_come_from_the_typed_qubit_table() -> None:
    q0 = _settings_from_config(load_config(), qubit="q0")
    q1 = _settings_from_config(load_config(), qubit="q1")

    assert q0.readout_frequency_ghz == 6.5
    assert q0.readout_power_dbm == -20.0
    assert q1.readout_frequency_ghz == 6.7
    assert q1.readout_power_dbm == -21.0


@pytest.mark.parametrize(
    ("invocation", "expected_coordinate_id", "expected_measurements"),
    [
        (
            RABI_TEMPLATE.bind(qubit="q0"),
            "drive_length",
            5,
        ),
        (
            READOUT_TEMPLATE.bind(qubit="q0"),
            "readout_frequency",
            5,
        ),
        (
            SQG_RB_TEMPLATE.bind(qubit="q0", seed=11).scan(
                CLIFFORD_COUNT,
                [4, 8],
            ),
            "clifford_count",
            2,
        ),
        (
            CZ_RB_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                seed=17,
            ).scan(CLIFFORD_COUNT, [2, 4]),
            "clifford_count",
            2,
        ),
    ],
)
def test_experiment_system_run_provider_python_api(
    tmp_path: Path,
    invocation: ExperimentInvocation,
    expected_coordinate_id: str,
    expected_measurements: int,
) -> None:
    run = _lab(tmp_path).prepare(invocation).run()
    measurements = run.data().measurements()

    assert run.manifest.status == "completed"
    assert measurements.dataset.dataset_schema.primary_coordinates == [
        expected_coordinate_id
    ]
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
        assert event.metrics["compute_status"] == "evaluated"
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
            [1, 2, 3],
        ),
        (
            TOY_SURFACE_CODE_ROUND_TEMPLATE.bind(rounds=2),
            "stabilizer_iq",
            [1, 2, 4],
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
        assert batch_event.metrics["compute_status"] == "evaluated"
        payload_id = cast("str", batch_event.metrics["payload_id"])
        assert payload_id.startswith(
            f"{_BACKEND_BATCH_SCOPE}/build-backend-batch-job/outputs/result.payload."
        )


def test_rejects_invalid_compute_edge_payload_schema_during_planning(
    tmp_path: Path,
) -> None:
    resolved = resolve_experiment(
        SQG_RB_TEMPLATE.bind(qubit="q0", seed=11).scan(CLIFFORD_COUNT, [4]),
        config_profile=load_config(),
    )
    sequence_node_id = "build-sqg-rb-sequence"
    experiment = resolved.experiment.model_copy(
        update={
            "compute_nodes": [
                node.model_copy(
                    update={
                        "result": node.result.model_copy(
                            update={
                                "value_type": ScalarType(PayloadType("pulse_program"))
                            }
                        )
                    }
                )
                if node.id.local_id == sequence_node_id
                else node
                for node in resolved.experiment.compute_nodes
            ]
        }
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(experiment, resolved.environment)

    assert len(caught.value.problems) == 1
    assert caught.value.problems[0].code == "compute_edge_type_mismatch"
    assert caught.value.problems[0].phase is ProblemPhase.PLANNING


def _lab(tmp_path: Path):
    return quantum_lab(
        workspace=tmp_path,
        config_profile=load_config(),
        virtual_lab_profile=EXPERIMENT_VIRTUAL_LAB_PROFILE,
    )
