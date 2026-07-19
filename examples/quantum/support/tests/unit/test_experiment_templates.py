from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import scopecat as sc
from scopecat.authoring import (
    ExperimentInvocation,
    ValueValidationError,
)
from scopecat.execution.local.program import (
    ApplyStateOperation,
    ComputeOperation,
    StateTarget,
)
from scopecat.execution.observation import RuntimePayloadObservation
from scopecat.execution.points import RunPoint
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.projection import MeasurementProjection
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.artifact import CommandPayload
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import PayloadRef

from quantum_lab_demo.experiments import (
    BACKEND_BATCH_TEMPLATE_ID,
    CZ_CHEVRON_TEMPLATE_ID,
    CZ_RB_TEMPLATE_ID,
    FLUX_BACKGROUND_RABI_TEMPLATE_ID,
    MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
    MULTIPLEXED_READOUT_TEMPLATE_ID,
    PARALLEL_GATE_SET_TEMPLATE_ID,
    QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    RABI_TEMPLATE_ID,
    READOUT_TEMPLATE_ID,
    SIMULTANEOUS_RABI_TEMPLATE_ID,
    SPECTATOR_CZ_TEMPLATE_ID,
    SQG_RB_TEMPLATE_ID,
    SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
    TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
)
from quantum_lab_demo.experiments.compute import build_parallel_gate_set_program
from quantum_lab_demo.experiments.payloads import (
    BackendBatchJob,
    CzChevronProgram,
    ParallelGateSetProgram,
    RenderedWaveformBundle,
    SurfaceCodeRoundProgram,
)
from quantum_lab_demo.experiments.points import (
    CLIFFORD_COUNT,
    COUPLER_AMPLITUDE,
    COUPLER_DURATION,
    COUPLER_PARKING_FLUX,
    GATE_DURATION,
    PHASE_OFFSET,
    QUBIT,
)
from quantum_lab_demo.experiments.templates import (
    BACKEND_BATCH_TEMPLATE,
    CZ_CHEVRON_TEMPLATE,
    CZ_RB_TEMPLATE,
    FLUX_BACKGROUND_RABI_TEMPLATE,
    MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE,
    MULTIPLEXED_READOUT_TEMPLATE,
    PARALLEL_GATE_SET_TEMPLATE,
    QND_REPEATED_MEASUREMENT_TEMPLATE,
    RABI_TEMPLATE,
    READOUT_TEMPLATE,
    SIMULTANEOUS_RABI_TEMPLATE,
    SPECTATOR_CZ_TEMPLATE,
    SQG_RB_TEMPLATE,
    SYSTEM_BACKGROUND_RABI_TEMPLATE,
    TOY_SURFACE_CODE_ROUND_TEMPLATE,
)
from quantum_lab_demo.lab import quantum_lab

from .demo_lab_experiment_testkit import (
    MaterializedLocalEffects,
    load_experiment_config,
    materialized_effects,
    measurement_projection_and_points,
    operations_of_type,
)


def test_template_constants_cover_experiment_system() -> None:
    experiment_templates = (
        RABI_TEMPLATE,
        SIMULTANEOUS_RABI_TEMPLATE,
        FLUX_BACKGROUND_RABI_TEMPLATE,
        SYSTEM_BACKGROUND_RABI_TEMPLATE,
        READOUT_TEMPLATE,
        MULTIPLEXED_READOUT_TEMPLATE,
        MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE,
        SQG_RB_TEMPLATE,
        CZ_RB_TEMPLATE,
        CZ_CHEVRON_TEMPLATE,
        SPECTATOR_CZ_TEMPLATE,
        PARALLEL_GATE_SET_TEMPLATE,
        TOY_SURFACE_CODE_ROUND_TEMPLATE,
        QND_REPEATED_MEASUREMENT_TEMPLATE,
        BACKEND_BATCH_TEMPLATE,
    )
    assert [experiment_template.id for experiment_template in experiment_templates] == [
        RABI_TEMPLATE_ID,
        SIMULTANEOUS_RABI_TEMPLATE_ID,
        FLUX_BACKGROUND_RABI_TEMPLATE_ID,
        SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
        READOUT_TEMPLATE_ID,
        MULTIPLEXED_READOUT_TEMPLATE_ID,
        MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
        SQG_RB_TEMPLATE_ID,
        CZ_RB_TEMPLATE_ID,
        CZ_CHEVRON_TEMPLATE_ID,
        SPECTATOR_CZ_TEMPLATE_ID,
        PARALLEL_GATE_SET_TEMPLATE_ID,
        TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
        QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
        BACKEND_BATCH_TEMPLATE_ID,
    ]
    invocation = RABI_TEMPLATE.bind(qubit="q0")
    assert invocation.template is not None
    assert invocation.template.id == RABI_TEMPLATE_ID


@pytest.mark.parametrize(
    ("label", "invocation", "template_id", "kind"),
    [
        (
            "rabi",
            RABI_TEMPLATE.bind(qubit="q0"),
            RABI_TEMPLATE_ID,
            "rabi",
        ),
        (
            "simultaneous_rabi",
            SIMULTANEOUS_RABI_TEMPLATE.bind(qubits=("q0", "q1")),
            SIMULTANEOUS_RABI_TEMPLATE_ID,
            "simultaneous_rabi",
        ),
        (
            "flux_background_rabi",
            FLUX_BACKGROUND_RABI_TEMPLATE.bind(qubit="q0"),
            FLUX_BACKGROUND_RABI_TEMPLATE_ID,
            "flux_background_rabi",
        ),
        (
            "system_background_rabi",
            SYSTEM_BACKGROUND_RABI_TEMPLATE.bind(qubit="q0"),
            SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
            "system_background_rabi",
        ),
        (
            "readout",
            READOUT_TEMPLATE.bind(qubit="q0"),
            READOUT_TEMPLATE_ID,
            "readout_frequency",
        ),
        (
            "multiplexed_readout",
            MULTIPLEXED_READOUT_TEMPLATE.bind(qubits=("q0", "q1")),
            MULTIPLEXED_READOUT_TEMPLATE_ID,
            "multiplexed_readout",
        ),
        (
            "multiplexed_readout_calibration",
            MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE.bind(qubits=("q0", "q1")),
            MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
            "multiplexed_readout_calibration",
        ),
        (
            "sqg_rb",
            SQG_RB_TEMPLATE.bind(qubit="q0", seed=11).scan(
                CLIFFORD_COUNT,
                [4, 8],
            ),
            SQG_RB_TEMPLATE_ID,
            "sqg_rb",
        ),
        (
            "cz_rb",
            CZ_RB_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                seed=17,
            ).scan(CLIFFORD_COUNT, [2, 4]),
            CZ_RB_TEMPLATE_ID,
            "cz_rb",
        ),
        (
            "cz_chevron",
            CZ_CHEVRON_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
            )
            .scan(COUPLER_DURATION, [24, 36], unit="ns")
            .scan(COUPLER_AMPLITUDE, [0.18, 0.24], unit="arb"),
            CZ_CHEVRON_TEMPLATE_ID,
            "cz_chevron",
        ),
        (
            "spectator_cz",
            SPECTATOR_CZ_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                background_couplers=("coupler-q2-q3",),
            )
            .scan(COUPLER_DURATION, [24], unit="ns")
            .scan(COUPLER_AMPLITUDE, [0.18], unit="arb"),
            SPECTATOR_CZ_TEMPLATE_ID,
            "spectator_cz_calibration",
        ),
        (
            "parallel_gate_set",
            PARALLEL_GATE_SET_TEMPLATE.bind().scan(
                GATE_DURATION,
                [28],
                unit="ns",
            ),
            PARALLEL_GATE_SET_TEMPLATE_ID,
            "parallel_gate_set",
        ),
        (
            "toy_surface_code_round",
            TOY_SURFACE_CODE_ROUND_TEMPLATE.bind(rounds=2),
            TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
            "toy_surface_code_round",
        ),
        (
            "qnd_repeated_measurement",
            QND_REPEATED_MEASUREMENT_TEMPLATE.bind(
                qubit="q0",
                rounds=3,
                shots=5,
            ),
            QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
            "qnd_repeated_measurement",
        ),
        (
            "backend_batch",
            BACKEND_BATCH_TEMPLATE.bind(
                logical_points=4,
                seed=5,
            ),
            BACKEND_BATCH_TEMPLATE_ID,
            "backend_batch_out_of_order",
        ),
    ],
)
def test_experiment_system_resolve_to_and_preview_invocation(
    tmp_path: Path,
    label: str,
    invocation: ExperimentInvocation,
    template_id: str,
    kind: str,
) -> None:
    config = load_experiment_config()

    resolved = resolve_experiment(
        invocation,
        config_profile=config,
    )

    assert resolved.template_id == template_id
    assert resolved.experiment.kind == kind

    projection, points = _measurement_projection(tmp_path, invocation, config)
    schema = projection.schema_for(points)
    assert schema is not None
    assert schema.primary_observables, label


def test_rabi_infers_default_scan_from_config(tmp_path: Path) -> None:
    preview = _materialized_effects(tmp_path, RABI_TEMPLATE.bind(qubit="q0"))

    assert len(preview.points) == 5
    assert preview.points[0].coordinates["drive_length"] == Quantity(
        value=10.0,
        unit="ns",
    )
    assert preview.points[-1].coordinates["drive_length"] == Quantity(
        value=90.0,
        unit="ns",
    )


def test_rabi_runtime_qubit_scan_drives_default_length_center(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)

    preview = lab.prepare(RABI_TEMPLATE).scan(QUBIT, ["q0", "q1"]).preview()

    assert preview.point_count == 10
    assert preview.coordinate_ids == ("qubit", "drive_length")
    assert preview.points[0].coordinates["drive_length"] == Quantity(
        value=10.0,
        unit="ns",
    )
    assert preview.points[4].coordinates["drive_length"] == Quantity(
        value=90.0,
        unit="ns",
    )
    assert preview.points[5].coordinates["drive_length"] == Quantity(
        value=8.0,
        unit="ns",
    )
    assert preview.points[-1].coordinates["drive_length"] == Quantity(
        value=88.0,
        unit="ns",
    )


def test_rabi_generates_point_local_pulse_programs(tmp_path: Path) -> None:
    config = load_experiment_config()
    invocation = RABI_TEMPLATE.bind(qubit="q0")
    preview = _materialized_effects(tmp_path, invocation, config)
    payloads = _run_observed_payloads(tmp_path, invocation)

    assert {
        (call.semantic_operation_id, call.payload_slot.schema_id)
        for point in preview.points
        for call in operations_of_type(point, ComputeOperation)
        if call.payload_slot is not None
    } == {
        (
            "rabi/render-rabi-waveforms",
            "pulse_program",
        )
    }
    assert len(payloads) == 5
    assert (
        len(
            [
                field
                for _, _, field in _state_fields(preview)
                if isinstance(field.value.root, PayloadRef)
                and field.field_path == "program"
            ]
        )
        == 5
    )
    payload = next(iter(payloads)).payload
    assert isinstance(payload, RenderedWaveformBundle)
    assert payload.source_program_id == "quantum_lab_demo.experiments.rabi_sequence.v1"
    assert payload.resource_id == "drive-stack"
    assert isinstance(payload.samples, np.ndarray)
    assert payload.samples.dtype == np.complex128
    assert payload.samples.shape == (10,)


def test_simultaneous_rabi_generates_entity_series_waveform_payloads(
    tmp_path: Path,
) -> None:
    invocation = SIMULTANEOUS_RABI_TEMPLATE.bind(qubits=("q0", "q1"))
    payloads = _run_observed_payloads(tmp_path, invocation)

    assert len(payloads) == 5
    payload = next(iter(payloads)).payload
    assert isinstance(payload, RenderedWaveformBundle)
    assert payload.resource_id == "drive-stack"
    assert payload.entity_ids == ("q0", "q1")
    assert isinstance(payload.samples, np.ndarray)
    assert payload.samples.dtype == np.complex128
    assert payload.samples.shape == (2, 18)


def test_flux_background_rabi_adds_background_state(tmp_path: Path) -> None:
    config = load_experiment_config()
    preview = _materialized_effects(
        tmp_path,
        FLUX_BACKGROUND_RABI_TEMPLATE.bind(
            qubit="q0",
            flux_bias=Quantity(value=0.05, unit="arb"),
        ),
        config,
    )

    assert (
        "coupler-stack",
        "set_flux_bias",
        "offset",
        Quantity(value=0.05, unit="arb"),
    ) in [
        (
            state.instrument_id,
            field.capability_id,
            field.field_path,
            field.value.root,
        )
        for _, state, field in _state_fields(preview)
    ]


def test_system_background_rabi_materializes_coupler_parking_table(
    tmp_path: Path,
) -> None:
    config = load_experiment_config()
    preview = _materialized_effects(
        tmp_path, SYSTEM_BACKGROUND_RABI_TEMPLATE.bind(qubit="q0"), config
    )

    fields = [
        field
        for point_index, state, field in _state_fields(preview)
        if point_index == 0
        and state.instrument_id == "coupler-stack"
        and field.capability_id == "set_flux_bias"
        if field.field_path == "offset"
    ]

    assert [
        (
            field.value.root,
            [
                (binding.entity_id, binding.channel_id)
                for binding in field.channel_bindings
            ],
        )
        for field in fields
    ] == [
        (
            Quantity(value=0.03, unit="arb"),
            [("coupler-q0-q1", "coupler-q0-q1")],
        ),
        (
            Quantity(value=0.028, unit="arb"),
            [("coupler-q2-q3", "coupler-q2-q3")],
        ),
    ]


def test_multiplexed_readout_is_single_point_entity_axis_record(
    tmp_path: Path,
) -> None:
    projection, points = _measurement_projection(
        tmp_path,
        MULTIPLEXED_READOUT_TEMPLATE.bind(qubits=("q0", "q1")),
    )

    observable = next(
        record for record in projection.records if record.id == "multiplexed_iq"
    )
    assert len(points) == 1
    assert observable.dtype == "complex128"
    assert observable.dims == ("point", "qubit")
    assert (len(points), *observable.shape[1:]) == (1, 2)


def test_multiplexed_readout_calibration_scans_shared_readout_pulse(
    tmp_path: Path,
) -> None:
    projection, points = _measurement_projection(
        tmp_path,
        MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE.bind(qubits=("q0", "q1")),
    )

    observable = next(
        record for record in projection.records if record.id == "multiplexed_iq"
    )
    assert len(points) == 5
    assert observable.dims == ("point", "qubit")
    assert (len(points), *observable.shape[1:]) == (5, 2)


def test_cz_chevron_generates_drive_and_coupler_payloads(tmp_path: Path) -> None:
    config = load_experiment_config()
    invocation = (
        CZ_CHEVRON_TEMPLATE.bind(
            control_qubit="q0",
            partner_qubit="q1",
        )
        .scan(COUPLER_DURATION, [24, 36], unit="ns")
        .scan(
            COUPLER_AMPLITUDE,
            [0.18, 0.24],
            unit="arb",
        )
    )
    preview = _materialized_effects(tmp_path, invocation, config)

    payloads = _run_observed_payloads(tmp_path, invocation)
    waveform_payloads = [
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, RenderedWaveformBundle)
    ]
    drive_payload = next(
        payload for payload in waveform_payloads if payload.samples.shape == (2, 24)
    )
    coupler_payload = next(
        payload for payload in waveform_payloads if payload.samples.shape == (24,)
    )
    cz_program = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, CzChevronProgram)
    )
    assert len(preview.points) == 4
    assert len(payloads) == 12
    assert (
        len(
            [
                field
                for _, _, field in _state_fields(preview)
                if isinstance(field.value.root, PayloadRef)
            ]
        )
        == 12
    )
    assert isinstance(drive_payload, RenderedWaveformBundle)
    assert isinstance(coupler_payload, RenderedWaveformBundle)
    assert isinstance(cz_program, CzChevronProgram)
    assert drive_payload.samples.shape == (2, 24)
    assert coupler_payload.samples.shape == (24,)
    assert drive_payload.channel_order == ("q0", "q1")
    assert cz_program.parameters == ("qubits", "two_qubit_gates")
    build_payload = next(
        call
        for call in operations_of_type(preview.points[0], ComputeOperation)
        if call.semantic_operation_id == ("cz_chevron/build-cz-chevron-program")
    )
    assert dict(build_payload.dependencies) == {
        "input_refs": ("control_qubit", "coupler", "partner_qubit"),
        "parameters": ("qubits", "two_qubit_gates"),
        "point_columns": ("coupler_amplitude", "coupler_duration"),
    }


def test_run_time_point_scan_extends_template_without_duplicate_template(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)

    preview = (
        lab.prepare(CZ_CHEVRON_TEMPLATE)
        .inputs(control_qubit="q0", partner_qubit="q1")
        .scan(COUPLER_DURATION, [24], unit="ns")
        .scan(COUPLER_AMPLITUDE, [0.18], unit="arb")
        .scan(PHASE_OFFSET, [0.0, 0.5], unit="rad")
        .preview()
    )

    assert preview.point_count == 2
    assert preview.coordinate_ids == (
        "coupler_duration",
        "coupler_amplitude",
        "phase_offset",
    )
    assert [point.coordinates["phase_offset"] for point in preview.points] == [
        Quantity(value=0.0, unit="rad"),
        Quantity(value=0.5, unit="rad"),
    ]


def test_workspace_preview_accepts_template_with_run_inputs_and_scans(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)

    prepared = (
        lab.prepare(CZ_CHEVRON_TEMPLATE)
        .inputs(control_qubit="q0", partner_qubit="q1")
        .scan(COUPLER_DURATION, [24], unit="ns")
        .scan(COUPLER_AMPLITUDE, [0.18], unit="arb")
        .scan(PHASE_OFFSET, [0.0, 0.5], unit="rad")
    )
    report = prepared.check()
    preview = prepared.preview()

    assert report.ok
    assert report.preview is not None
    assert preview.point_count == 2
    assert preview.coordinate_ids == (
        "coupler_duration",
        "coupler_amplitude",
        "phase_offset",
    )


def test_run_time_parameter_scan_extends_template_without_duplicate_template(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)

    preview = (
        lab.prepare(CZ_CHEVRON_TEMPLATE)
        .inputs(control_qubit="q0", partner_qubit="q1")
        .scan(COUPLER_DURATION, [24], unit="ns")
        .scan(COUPLER_AMPLITUDE, [0.18], unit="arb")
        .scan(
            sc.param_axis(
                COUPLER_PARKING_FLUX,
                sc.param_row(
                    "two_qubit_gates",
                    control_qubit=sc.input(
                        "control_qubit",
                        sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")),
                    ),
                    partner_qubit=sc.input(
                        "partner_qubit",
                        sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")),
                    ),
                    gate="cz",
                ),
                "coupler_parking_flux",
                [0.02, 0.04],
                unit="arb",
            )
        )
        .preview()
    )

    assert preview.point_count == 2
    assert preview.coordinate_ids == (
        "coupler_duration",
        "coupler_amplitude",
        "parking_flux",
    )
    assert [point.coordinates["parking_flux"] for point in preview.points] == [
        Quantity(value=0.02, unit="arb"),
        Quantity(value=0.04, unit="arb"),
    ]


def test_spectator_cz_adds_background_state(tmp_path: Path) -> None:
    config = load_experiment_config()
    preview = _materialized_effects(
        tmp_path,
        SPECTATOR_CZ_TEMPLATE.bind(
            control_qubit="q0",
            partner_qubit="q1",
            background_couplers=("coupler-q2-q3",),
            spectator_flux_bias=Quantity(value=0.025, unit="arb"),
        )
        .scan(COUPLER_DURATION, [24], unit="ns")
        .scan(COUPLER_AMPLITUDE, [0.18], unit="arb"),
        config,
    )

    assert len(preview.points) == 1
    assert (
        "coupler-stack",
        "set_flux_bias",
        "offset",
        Quantity(value=0.025, unit="arb"),
    ) in [
        (
            state.instrument_id,
            field.capability_id,
            field.field_path,
            field.value.root,
        )
        for _, state, field in _state_fields(preview)
    ]


def test_parallel_gate_set_routes_disjoint_pairs(tmp_path: Path) -> None:
    payloads = _run_observed_payloads(
        tmp_path,
        PARALLEL_GATE_SET_TEMPLATE.bind().scan(
            GATE_DURATION,
            [28],
            unit="ns",
        ),
    )
    gate_program = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, ParallelGateSetProgram)
    )
    waveform_payloads = [
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, RenderedWaveformBundle)
    ]
    drive_payload = next(
        payload
        for payload in waveform_payloads
        if payload.entity_ids == ("q0", "q1", "q2", "q3")
    )
    coupler_payload = next(
        payload
        for payload in waveform_payloads
        if payload.entity_ids == ("coupler-q0-q1", "coupler-q2-q3")
    )

    assert isinstance(gate_program, ParallelGateSetProgram)
    assert len(gate_program.gates) == 2
    assert isinstance(drive_payload, RenderedWaveformBundle)
    assert isinstance(coupler_payload, RenderedWaveformBundle)
    assert drive_payload.entity_ids == ("q0", "q1", "q2", "q3")
    assert coupler_payload.entity_ids == ("coupler-q0-q1", "coupler-q2-q3")
    assert drive_payload.samples.shape == (4, 28)
    assert coupler_payload.samples.shape == (2, 28)


@pytest.mark.parametrize("gate_count", (1, 3))
def test_parallel_gate_compute_accepts_arbitrary_table_cardinality(
    gate_count: int,
) -> None:
    rows = [
        {
            "control_qubit": f"q{2 * index}",
            "partner_qubit": f"q{2 * index + 1}",
            "coupler": f"coupler-{index}",
            "coupler_parking_flux": Quantity(value=0.02 + index * 0.001, unit="arb"),
            "control_frequency": Quantity(value=5.0 + index * 0.1, unit="GHz"),
            "partner_frequency": Quantity(value=5.05 + index * 0.1, unit="GHz"),
        }
        for index in range(gate_count)
    ]

    program = build_parallel_gate_set_program(
        gates=rows,
        gate_duration=Quantity(value=28.0, unit="ns"),
    )

    assert len(program.gates) == gate_count
    assert [gate.control_qubit for gate in program.gates] == [
        f"q{2 * index}" for index in range(gate_count)
    ]
    assert all(
        gate.duration == Quantity(value=28.0, unit="ns") for gate in program.gates
    )


@pytest.mark.parametrize(
    ("gates", "expected_qubits", "expected_couplers"),
    (
        pytest.param(
            (
                {
                    "control_qubit": "q0",
                    "partner_qubit": "q1",
                    "gate": "cz",
                },
            ),
            ("q0", "q1"),
            ("coupler-q0-q1",),
            id="one-row",
        ),
        pytest.param(
            (
                {
                    "control_qubit": "q2",
                    "partner_qubit": "q3",
                    "gate": "cz",
                },
                {
                    "control_qubit": "q0",
                    "partner_qubit": "q1",
                    "gate": "cz",
                },
            ),
            ("q2", "q3", "q0", "q1"),
            ("coupler-q2-q3", "coupler-q0-q1"),
            id="reordered-two-rows",
        ),
    ),
)
def test_parallel_gate_table_drives_program_and_resource_route_order(
    tmp_path: Path,
    gates: tuple[dict[str, str], ...],
    expected_qubits: tuple[str, ...],
    expected_couplers: tuple[str, ...],
) -> None:
    payloads = _run_observed_payloads(
        tmp_path,
        PARALLEL_GATE_SET_TEMPLATE.bind(gates=gates).scan(
            GATE_DURATION,
            [28],
            unit="ns",
        ),
    )
    gate_program = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, ParallelGateSetProgram)
    )
    waveform_payloads = {
        payload.payload.resource_id: payload.payload
        for payload in payloads
        if isinstance(payload.payload, RenderedWaveformBundle)
    }

    assert [
        (gate.control_qubit, gate.partner_qubit, gate.coupler)
        for gate in gate_program.gates
    ] == [
        (control, partner, coupler)
        for (control, partner), coupler in zip(
            zip(expected_qubits[::2], expected_qubits[1::2], strict=True),
            expected_couplers,
            strict=True,
        )
    ]
    assert waveform_payloads["drive-stack"].entity_ids == expected_qubits
    assert waveform_payloads["coupler-stack"].entity_ids == expected_couplers
    assert waveform_payloads["drive-stack"].samples.shape == (
        len(expected_qubits),
        28,
    )
    assert waveform_payloads["coupler-stack"].samples.shape == (
        len(expected_couplers),
        28,
    )


def test_toy_surface_code_round_uses_round_and_entity_axes(tmp_path: Path) -> None:
    config = load_experiment_config()
    invocation = TOY_SURFACE_CODE_ROUND_TEMPLATE.bind(rounds=2)
    projection, points = _measurement_projection(tmp_path, invocation, config)

    payloads = _run_observed_payloads(tmp_path, invocation)
    surface_program = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, SurfaceCodeRoundProgram)
    )
    observable = next(
        record for record in projection.records if record.id == "stabilizer_iq"
    )

    assert isinstance(surface_program, SurfaceCodeRoundProgram)
    assert surface_program.patch_qubits == ("q0", "q1", "q2", "q3")
    assert len(surface_program.schedule) == 4
    assert observable.dims == ("point", "round", "qubit")
    assert (len(points), *observable.shape[1:]) == (1, 2, 4)


def test_qnd_repeated_measurement_keeps_dense_round_shot_array(
    tmp_path: Path,
) -> None:
    projection, points = _measurement_projection(
        tmp_path,
        QND_REPEATED_MEASUREMENT_TEMPLATE.bind(
            qubit="q0",
            rounds=3,
            shots=5,
        ),
    )

    observable = next(record for record in projection.records if record.id == "qnd_iq")

    assert len(points) == 1
    assert observable.dims == ("point", "round", "shot")
    assert (len(points), *observable.shape[1:]) == (1, 3, 5)


def test_backend_batch_keeps_logical_backend_points_inside_payload_and_record(
    tmp_path: Path,
) -> None:
    config = load_experiment_config()
    invocation = BACKEND_BATCH_TEMPLATE.bind(
        logical_points=4,
        seed=5,
    )
    projection, points = _measurement_projection(tmp_path, invocation, config)

    payloads = _run_observed_payloads(tmp_path, invocation)
    batch_job = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, BackendBatchJob)
    )
    observable = next(
        record for record in projection.records if record.id == "backend_probabilities"
    )

    assert isinstance(batch_job, BackendBatchJob)
    assert batch_job.logical_points == 4
    assert sorted(batch_job.returned_order) == [0, 1, 2, 3]
    assert batch_job.returned_order != (0, 1, 2, 3)
    assert observable.dims == ("point", "backend_point")
    assert (len(points), *observable.shape[1:]) == (1, 4)


def test_template_rejects_removed_scan_input_alias(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            SQG_RB_TEMPLATE.bind(qubit="q0", lengths=[]),
            config_profile=load_experiment_config(),
        )

    assert error.value.problems[0].code == "experiment_template_unknown_input"


def test_scan_values_are_checked_against_the_typed_point() -> None:
    with pytest.raises(ValueValidationError) as error:
        SQG_RB_TEMPLATE.bind(qubit="q0").scan(CLIFFORD_COUNT, [0])

    assert error.value.path == ("scan", "values", 0)
    assert error.value.reason == "value must be at least 1"


def _run_observed_payloads(
    tmp_path: Path,
    invocation: ExperimentInvocation,
) -> list[CommandPayload]:
    observations: list[RuntimePayloadObservation] = []
    quantum_lab(workspace=tmp_path).prepare(invocation).run(
        payload_observer=observations.append,
    )
    return [observation.payload for observation in observations]


def _materialized_effects(
    tmp_path: Path,
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot | None = None,
) -> MaterializedLocalEffects:
    del tmp_path
    return materialized_effects(invocation, config=config)


def _measurement_projection(
    tmp_path: Path,
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot | None = None,
) -> tuple[MeasurementProjection, tuple[RunPoint, ...]]:
    del tmp_path
    return measurement_projection_and_points(invocation, config=config)


def _state_fields(
    plan: MaterializedLocalEffects,
) -> tuple[tuple[int, ApplyStateOperation, StateTarget], ...]:
    return tuple(
        (point.point_index, state, field)
        for point in plan.points
        for state in operations_of_type(point, ApplyStateOperation)
        for field in state.targets
    )
