from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import scopecat as sc
from demo_lab_experiment_testkit import load_experiment_config
from scopecat.authoring import (
    ExperimentInvocation,
    resolve_experiment,
)
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    ExperimentSpec,
)
from scopecat.instruments import RuntimePayloadObservation
from scopecat.models.artifact import CommandPayload
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity

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
from quantum_lab_demo.experiments.payloads import (
    BackendBatchJob,
    CzChevronProgram,
    ParallelGateSetProgram,
    RenderedWaveformBundle,
    SurfaceCodeRoundProgram,
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
            SIMULTANEOUS_RABI_TEMPLATE.bind(qubits=sc.entity_array(("q0", "q1"))),
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
            MULTIPLEXED_READOUT_TEMPLATE.bind(qubits=sc.entity_array(("q0", "q1"))),
            MULTIPLEXED_READOUT_TEMPLATE_ID,
            "multiplexed_readout",
        ),
        (
            "multiplexed_readout_calibration",
            MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE.bind(
                qubits=sc.entity_array(("q0", "q1"))
            ),
            MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
            "multiplexed_readout_calibration",
        ),
        (
            "sqg_rb",
            SQG_RB_TEMPLATE.bind(qubit="q0", lengths=[4, 8], seed=11),
            SQG_RB_TEMPLATE_ID,
            "sqg_rb",
        ),
        (
            "cz_rb",
            CZ_RB_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                lengths=[2, 4],
                seed=17,
            ),
            CZ_RB_TEMPLATE_ID,
            "cz_rb",
        ),
        (
            "cz_chevron",
            CZ_CHEVRON_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                durations=[24, 36],
                amplitudes=[0.18, 0.24],
            ),
            CZ_CHEVRON_TEMPLATE_ID,
            "cz_chevron",
        ),
        (
            "spectator_cz",
            SPECTATOR_CZ_TEMPLATE.bind(
                control_qubit="q0",
                partner_qubit="q1",
                background_couplers=sc.entity_array(("coupler-q2-q3",)),
                durations=[24],
                amplitudes=[0.18],
            ),
            SPECTATOR_CZ_TEMPLATE_ID,
            "spectator_cz_calibration",
        ),
        (
            "parallel_gate_set",
            PARALLEL_GATE_SET_TEMPLATE.bind(durations=[28]),
            PARALLEL_GATE_SET_TEMPLATE_ID,
            "parallel_gate_set",
        ),
        (
            "toy_surface_code_round",
            TOY_SURFACE_CODE_ROUND_TEMPLATE.bind(
                rounds=sc.Quantity(value=2.0, unit="count")
            ),
            TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
            "toy_surface_code_round",
        ),
        (
            "qnd_repeated_measurement",
            QND_REPEATED_MEASUREMENT_TEMPLATE.bind(
                qubit="q0",
                rounds=sc.Quantity(value=3.0, unit="count"),
                shots=sc.Quantity(value=5.0, unit="count"),
            ),
            QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
            "qnd_repeated_measurement",
        ),
        (
            "backend_batch",
            BACKEND_BATCH_TEMPLATE.bind(
                logical_points=sc.Quantity(value=4.0, unit="count"),
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
        workspace=tmp_path,
        config_profile=config,
    )

    assert resolved.template_id == template_id
    assert isinstance(resolved.experiment, ExperimentSpec)
    assert resolved.experiment.kind == kind

    preview = _preview(tmp_path, invocation, config)
    assert preview.primary_observables, label
    assert preview.template_id == template_id


def test_rabi_infers_default_scan_from_config(tmp_path: Path) -> None:
    preview = _preview(tmp_path, RABI_TEMPLATE.bind(qubit="q0"))

    assert preview.point_count == 5
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

    preview = lab.prepare(RABI_TEMPLATE).scan("qubit", ["q0", "q1"]).preview()

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
    assert [route.resource_id for route in preview.routes[0].resolved[:2]] == [
        "drive-stack",
        "drive-stack",
    ]


def test_rabi_generates_point_local_pulse_programs(tmp_path: Path) -> None:
    config = load_experiment_config()
    invocation = RABI_TEMPLATE.bind(qubit="q0")
    preview = _preview(tmp_path, invocation, config)
    payloads = _run_observed_payloads(tmp_path, invocation)

    assert [(item.node_id, item.kind) for item in preview.payloads] == [
        ("render-rabi-waveforms", "pulse_program")
    ]
    assert len(payloads) == 5
    assert (
        len(
            [
                field
                for field in preview.state_fields
                if field.value_kind == "payload" and field.field_path == "program"
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


def test_simultaneous_rabi_generates_entity_array_waveform_payloads(
    tmp_path: Path,
) -> None:
    config = load_experiment_config()
    invocation = SIMULTANEOUS_RABI_TEMPLATE.bind(qubits=sc.entity_array(("q0", "q1")))
    resolved = resolve_experiment(
        invocation,
        workspace=tmp_path,
        config_profile=config,
    )

    assert isinstance(resolved.experiment, ExperimentSpec)
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
    preview = _preview(
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
            field.resource_id,
            field.capability_id,
            field.field_path,
            field.value,
        )
        for field in preview.state_fields
    ]


def test_system_background_rabi_materializes_coupler_parking_table(
    tmp_path: Path,
) -> None:
    config = load_experiment_config()
    preview = _preview(
        tmp_path, SYSTEM_BACKGROUND_RABI_TEMPLATE.bind(qubit="q0"), config
    )

    fields = [
        field
        for field in preview.state_fields
        if field.point_index == 0
        and field.resource_id == "coupler-stack"
        and field.capability_id == "set_flux_bias"
        if field.field_path == "offset"
    ]

    assert [
        (
            field.value,
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
    preview = _preview(
        tmp_path,
        MULTIPLEXED_READOUT_TEMPLATE.bind(qubits=sc.entity_array(("q0", "q1"))),
    )

    observable = next(
        record for record in preview.records if record.id == "multiplexed_iq"
    )
    assert preview.point_count == 1
    assert observable.dtype == "complex128"
    assert observable.dims == ("point", "qubit")
    assert observable.shape == (1, 2)


def test_multiplexed_readout_calibration_scans_shared_readout_pulse(
    tmp_path: Path,
) -> None:
    preview = _preview(
        tmp_path,
        MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE.bind(
            qubits=sc.entity_array(("q0", "q1"))
        ),
    )

    observable = next(
        record for record in preview.records if record.id == "multiplexed_iq"
    )
    assert preview.point_count == 5
    assert observable.dims == ("point", "qubit")
    assert observable.shape == (5, 2)


def test_cz_chevron_generates_drive_and_coupler_payloads(tmp_path: Path) -> None:
    config = load_experiment_config()
    invocation = CZ_CHEVRON_TEMPLATE.bind(
        control_qubit="q0",
        partner_qubit="q1",
        durations=[24, 36],
        amplitudes=[0.18, 0.24],
    )
    preview = _preview(tmp_path, invocation, config)

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
    assert preview.point_count == 4
    assert len(payloads) == 12
    assert (
        len([field for field in preview.state_fields if field.value_kind == "payload"])
        == 12
    )
    assert isinstance(drive_payload, RenderedWaveformBundle)
    assert isinstance(coupler_payload, RenderedWaveformBundle)
    assert isinstance(cz_program, CzChevronProgram)
    assert drive_payload.samples.shape == (2, 24)
    assert coupler_payload.samples.shape == (24,)
    assert drive_payload.channel_order == ("q0", "q1")
    assert cz_program.parameter_tables == ("qubits", "two_qubit_gates")
    build_payload = next(
        payload
        for payload in preview.payloads
        if payload.node_id == "build-cz-chevron-program"
    )
    assert build_payload.dependencies == {
        "input_refs": ("control_qubit", "coupler", "partner_qubit"),
        "parameter_tables": ("qubits", "two_qubit_gates"),
        "point_columns": ("coupler_amplitude", "coupler_duration"),
    }


def test_run_time_point_scan_extends_template_without_duplicate_template(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)

    preview = (
        lab.prepare(CZ_CHEVRON_TEMPLATE)
        .inputs(control_qubit="q0", partner_qubit="q1")
        .scan("coupler_duration", [24], unit="ns")
        .scan("coupler_amplitude", [0.18], unit="arb")
        .scan("phase_offset", [0.0, 0.5], unit="rad")
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

    preview = (
        lab.prepare(CZ_CHEVRON_TEMPLATE)
        .inputs(control_qubit="q0", partner_qubit="q1")
        .scan("coupler_duration", [24], unit="ns")
        .scan("coupler_amplitude", [0.18], unit="arb")
        .scan("phase_offset", [0.0, 0.5], unit="rad")
        .preview()
    )

    assert preview.template_id == CZ_CHEVRON_TEMPLATE_ID
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
        .scan("coupler_duration", [24], unit="ns")
        .scan("coupler_amplitude", [0.18], unit="arb")
        .scan(
            sc.param_axis(
                sc.param_row(
                    "two_qubit_gates",
                    control_qubit=sc.input("control_qubit"),
                    partner_qubit=sc.input("partner_qubit"),
                    gate="cz",
                ),
                "coupler_parking_flux",
                [0.02, 0.04],
                axis_id="parking_flux",
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
    preview = _preview(
        tmp_path,
        SPECTATOR_CZ_TEMPLATE.bind(
            control_qubit="q0",
            partner_qubit="q1",
            background_couplers=sc.entity_array(("coupler-q2-q3",)),
            durations=[24],
            amplitudes=[0.18],
            spectator_flux_bias=Quantity(value=0.025, unit="arb"),
        ),
        config,
    )

    assert preview.point_count == 1
    assert (
        "coupler-stack",
        "set_flux_bias",
        "offset",
        Quantity(value=0.025, unit="arb"),
    ) in [
        (
            field.resource_id,
            field.capability_id,
            field.field_path,
            field.value,
        )
        for field in preview.state_fields
    ]


def test_parallel_gate_set_routes_disjoint_pairs(tmp_path: Path) -> None:
    payloads = _run_observed_payloads(
        tmp_path,
        PARALLEL_GATE_SET_TEMPLATE.bind(durations=[28]),
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


def test_toy_surface_code_round_uses_round_and_entity_axes(tmp_path: Path) -> None:
    config = load_experiment_config()
    invocation = TOY_SURFACE_CODE_ROUND_TEMPLATE.bind(
        rounds=sc.Quantity(value=2.0, unit="count")
    )
    preview = _preview(tmp_path, invocation, config)

    payloads = _run_observed_payloads(tmp_path, invocation)
    surface_program = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, SurfaceCodeRoundProgram)
    )
    observable = next(
        record for record in preview.records if record.id == "stabilizer_iq"
    )

    assert isinstance(surface_program, SurfaceCodeRoundProgram)
    assert surface_program.patch_qubits == ("q0", "q1", "q2", "q3")
    assert len(surface_program.schedule) == 4
    assert observable.dims == ("point", "round", "qubit")
    assert observable.shape == (1, 2, 4)


def test_qnd_repeated_measurement_keeps_dense_round_shot_array(
    tmp_path: Path,
) -> None:
    preview = _preview(
        tmp_path,
        QND_REPEATED_MEASUREMENT_TEMPLATE.bind(
            qubit="q0",
            rounds=sc.Quantity(value=3.0, unit="count"),
            shots=sc.Quantity(value=5.0, unit="count"),
        ),
    )

    observable = next(record for record in preview.records if record.id == "qnd_iq")

    assert preview.point_count == 1
    assert observable.dims == ("point", "round", "shot")
    assert observable.shape == (1, 3, 5)


def test_backend_batch_keeps_logical_backend_points_inside_payload_and_record(
    tmp_path: Path,
) -> None:
    config = load_experiment_config()
    invocation = BACKEND_BATCH_TEMPLATE.bind(
        logical_points=sc.Quantity(value=4.0, unit="count"),
        seed=5,
    )
    preview = _preview(tmp_path, invocation, config)

    payloads = _run_observed_payloads(tmp_path, invocation)
    batch_job = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, BackendBatchJob)
    )
    observable = next(
        record for record in preview.records if record.id == "backend_probabilities"
    )

    assert isinstance(batch_job, BackendBatchJob)
    assert batch_job.logical_points == 4
    assert sorted(batch_job.returned_order) == [0, 1, 2, 3]
    assert batch_job.returned_order != (0, 1, 2, 3)
    assert observable.dims == ("point", "backend_point")
    assert observable.shape == (1, 4)


def test_template_reports_empty_sequence_axis(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            SQG_RB_TEMPLATE.bind(qubit="q0", lengths=[]),
            workspace=tmp_path,
            config_profile=load_experiment_config(),
        )

    assert error.value.diagnostics[0].code == "module_point_values_empty"


def _run_observed_payloads(
    tmp_path: Path,
    invocation: ExperimentInvocation,
) -> list[CommandPayload]:
    observations: list[RuntimePayloadObservation] = []
    quantum_lab(workspace=tmp_path).prepare(invocation).run(
        payload_observer=observations.append,
    )
    return [observation.payload for observation in observations]


def _preview(
    tmp_path: Path,
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot | None = None,
):
    return (
        quantum_lab(
            workspace=tmp_path,
            config_profile=config or load_experiment_config(),
        )
        .prepare(invocation)
        .preview()
    )
