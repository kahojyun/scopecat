from __future__ import annotations

from pathlib import Path

import pytest
import scopecat as sc
from demo_lab_test_paths import (
    EXPERIMENT_FIXTURE_DIR,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
)
from scopecat.authoring import ExperimentInvocation, resolve_experiment
from scopecat.config_profiles import load_config_profile
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.instruments import RuntimeEvent
from scopecat.models.config import ConfigProfileSnapshot

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
from quantum_lab_demo.lab import quantum_lab


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")


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
            SQG_RB_TEMPLATE.bind(qubit="q0", lengths=[4, 8], seed=11),
            "clifford_count",
            2,
        ),
        (
            CZ_RB_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                lengths=[2, 4],
                seed=17,
            ),
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
    run = _lab(tmp_path).run(
        invocation,
    )
    measurements = run.data().measurements()

    assert run.manifest.status == "completed"
    assert measurements.dataset.dataset_schema.primary_coordinates == [
        expected_coordinate_id
    ]
    assert len(measurements.dataset.records) == expected_measurements


def test_cz_chevron_emits_waveform_compute_summaries(tmp_path: Path) -> None:
    events: list[RuntimeEvent] = []

    run = _lab(tmp_path).run(
        CZ_CHEVRON_TEMPLATE.bind(
            control_qubit="q0",
            partner_qubit="q1",
            durations=[24],
            amplitudes=[0.18],
        ),
        event_sink=events.append,
    )

    compute_summaries = [
        event.summary for event in events if event.kind == "compute_finished"
    ]
    drive_summary = next(
        summary
        for summary in compute_summaries
        if summary.get("node_id") == "render-cz-chevron-drive-waveforms"
    )
    program_summary = next(
        summary
        for summary in compute_summaries
        if summary.get("node_id") == "build-cz-chevron-program"
    )

    assert run.manifest.status == "completed"
    assert program_summary["fields"] == [
        "control_qubit",
        "partner_qubit",
        "coupler",
        "drive_pulses",
        "coupler_pulse",
        "sample_rate_hz",
        "compiler_id",
        "parameter_tables",
    ]
    assert program_summary["dependencies"] == {
        "input_refs": ["control_qubit", "coupler", "partner_qubit"],
        "parameter_tables": ["qubits", "two_qubit_gates"],
        "point_columns": ["coupler_amplitude", "coupler_duration"],
    }
    assert drive_summary["sample_shape"] == [2, 24]
    assert drive_summary["dependencies"] == {
        "input_refs": ["control_qubit", "coupler", "partner_qubit"],
        "parameter_tables": ["qubits", "two_qubit_gates"],
        "point_columns": ["coupler_amplitude", "coupler_duration"],
        "routes": ["drive"],
        "upstream_compute": ["build-cz-chevron-program"],
    }
    assert drive_summary["sample_dtype"] == "complex128"
    assert drive_summary["channel_count"] == 2
    assert drive_summary["entity_ids"] == ["q0", "q1"]


@pytest.mark.parametrize(
    ("invocation", "observable_id", "shape"),
    [
        (
            QND_REPEATED_MEASUREMENT_TEMPLATE.bind(
                qubit="q0",
                rounds=sc.Quantity(value=2.0, unit="count"),
                shots=sc.Quantity(value=3.0, unit="count"),
            ),
            "qnd_iq",
            [1, 2, 3],
        ),
        (
            TOY_SURFACE_CODE_ROUND_TEMPLATE.bind(
                rounds=sc.Quantity(value=2.0, unit="count")
            ),
            "stabilizer_iq",
            [1, 2, 4],
        ),
        (
            BACKEND_BATCH_TEMPLATE.bind(
                logical_points=sc.Quantity(value=4.0, unit="count"),
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

    run = _lab(tmp_path).run(
        invocation,
        event_sink=events.append,
    )
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
        batch_summary = next(
            event.summary
            for event in events
            if event.kind == "compute_finished"
            and event.summary.get("node_id") == "build-backend-batch-job"
        )
        assert batch_summary["fields"] == [
            "logical_points",
            "submitted_point_uids",
            "returned_order",
            "seed",
            "compiler_id",
        ]


def test_rejects_invalid_payload_kind(
    tmp_path: Path,
) -> None:
    resolved = resolve_experiment(
        SQG_RB_TEMPLATE.bind(qubit="q0", lengths=[4], seed=11),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    assert isinstance(resolved.experiment, ExperimentSpec)
    sequence_state = resolved.experiment.state[0]
    assert sequence_state.value is not None
    experiment = resolved.experiment.model_copy(
        update={
            "state": [
                sequence_state.model_copy(
                    update={
                        "value": sequence_state.value.model_copy(
                            update={
                                "value": {
                                    "kind": "compute_result",
                                    "node_id": "build-sqg-rb-sequence",
                                    "payload_kind": "pulse_program",
                                }
                            }
                        )
                    }
                ),
                *resolved.experiment.state[1:],
            ]
        }
    )

    with pytest.raises(ValidationFailed) as error:
        _lab(tmp_path).run(
            experiment,
        )

    assert error.value.diagnostics[0].code == "instrument_driver_payload_kind_mismatch"


def _lab(tmp_path: Path):
    return quantum_lab(
        workspace=tmp_path,
        config_profile=load_config(),
        virtual_lab_profile=EXPERIMENT_VIRTUAL_LAB_PROFILE,
    )
