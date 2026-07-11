from __future__ import annotations

from pathlib import Path

import pytest
from demo_lab_test_paths import (
    EXPERIMENT_FIXTURE_DIR,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
)
from scopecat._compiler.binding import bind_program
from scopecat._execution.executor import execute_run
from scopecat.authoring import (
    ExperimentInvocation,
    PayloadType,
    ScalarType,
)
from scopecat.authoring._resolution import resolve_experiment
from scopecat.config_profiles import load_config_profile
from scopecat.errors import ValidationFailed
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
from quantum_lab_demo.experiments.points import (
    CLIFFORD_COUNT,
    COUPLER_AMPLITUDE,
    COUPLER_DURATION,
)
from quantum_lab_demo.experiments.readout_responses import _settings_from_config
from quantum_lab_demo.lab import quantum_lab

_CZ_CHEVRON_SCOPE = "quantum_lab_demo.experiments.two_qubit.cz_chevron[0]"
_BACKEND_BATCH_SCOPE = "quantum_lab_demo.experiments.backend.batch[0]"


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

    compute_summaries = [
        event.summary for event in events if event.kind == "compute_finished"
    ]
    drive_summary = next(
        summary
        for summary in compute_summaries
        if summary.get("kernel_id")
        == f"{_CZ_CHEVRON_SCOPE}/render-cz-chevron-drive-waveforms"
    )
    program_summary = next(
        summary
        for summary in compute_summaries
        if summary.get("kernel_id") == f"{_CZ_CHEVRON_SCOPE}/build-cz-chevron-program"
    )

    assert run.manifest.status == "completed"
    for summary in (program_summary, drive_summary):
        kernel_id = summary["kernel_id"]
        assert summary["compute_status"] == "evaluated"
        assert summary["payload_id"].startswith(f"{kernel_id}.payload.")
        assert summary["operation_id"].endswith(f".compute.{kernel_id}")


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
        batch_summary = next(
            event.summary
            for event in events
            if event.kind == "compute_finished"
            and event.summary.get("kernel_id")
            == f"{_BACKEND_BATCH_SCOPE}/build-backend-batch-job"
        )
        assert batch_summary["compute_status"] == "evaluated"
        assert batch_summary["payload_id"].startswith(
            f"{_BACKEND_BATCH_SCOPE}/build-backend-batch-job.payload."
        )


def test_rejects_invalid_payload_schema(
    tmp_path: Path,
) -> None:
    resolved = resolve_experiment(
        SQG_RB_TEMPLATE.bind(qubit="q0", seed=11).scan(CLIFFORD_COUNT, [4]),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    sequence_node_id = "build-sqg-rb-sequence"
    experiment = resolved.experiment.model_copy(
        update={
            "compute_nodes": [
                node.model_copy(
                    update={"output_type": ScalarType(PayloadType("pulse_program"))}
                )
                if node.id.local_id == sequence_node_id
                else node
                for node in resolved.experiment.compute_nodes
            ]
        }
    )

    lab = _lab(tmp_path)
    assert lab.instrument_provider is not None
    plan = bind_program(experiment, resolved.environment)
    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=resolved.config,
            plan=plan,
            request=resolved.request,
            instrument_provider=lab.instrument_provider,
            workspace=tmp_path,
            config_source=resolved.config_source,
        )

    assert error.value.diagnostics[0].code == "instrument_driver_field_value_mismatch"


def _lab(tmp_path: Path):
    return quantum_lab(
        workspace=tmp_path,
        config_profile=load_config(),
        virtual_lab_profile=EXPERIMENT_VIRTUAL_LAB_PROFILE,
    )
