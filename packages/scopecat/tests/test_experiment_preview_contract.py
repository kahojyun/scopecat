from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import (
    TypedComputeNode,
    TypedPointSource,
    compute_result,
    observable,
    overlay_parameter_cell,
    record_axis,
    set_state_field,
    typed_program,
)
from scopecat._relations import RelationExpr, col, grid, linspace, param, table
from scopecat.models.parameter import Quantity
from scopecat.value_types import Payload, Scalar, String
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Table as TableType
from tests.support.experiment_preview import preview_contract, preview_result
from tests.support.parameter_fixtures import parameters as _parameters


def _point_source(expr: RelationExpr) -> TypedPointSource:
    return TypedPointSource(
        expr=expr,
        value_type=TableType(columns=(), allow_extra_columns=True),
    )


def test_preview_contract_summarizes_points_state_and_records() -> None:
    spec = typed_program(
        id="readout-frequency-calibration",
        kind="readout.frequency_scan",
        point_source=_point_source(
            grid(
                readout=table("readout_devices").filter(col("enabled").eq(True)),
                readout_frequency=linspace(5.9, 6.0, 2, unit="GHz"),
            )
        ),
        parameter_overlays=[
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": col("readout.device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=col("readout_frequency"),
                value_type=Scalar(QuantityType(unit="GHz")),
            )
        ],
        state=[
            set_state_field(
                col("readout.resource_id"),
                capability_id="pulse",
                field_path="frequency",
                value=param(
                    "readout_devices",
                    key={"device_id": col("readout.device_id")},
                    column="frequency",
                ),
            )
        ],
        records=[observable("signal", unit="ratio")],
    )

    preview = preview_contract(spec, _parameters())

    assert preview.point_count == 2
    assert preview.coordinate_ids == ("readout_frequency",)
    assert [point.coordinates["readout_frequency"] for point in preview.points] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
    assert [change.after for change in preview.state_changes] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
    assert [
        (
            record.id,
            record.kind,
            record.source,
            record.unit,
            record.dtype,
            record.dims,
            record.shape,
        )
        for record in preview.records
    ] == [
        (
            "signal",
            "observable",
            "instrument",
            "ratio",
            "float64",
            ("point",),
            (2,),
        )
    ]
    assert preview.dataset_dimensions == {"point": 2}
    assert preview.primary_observables == ("signal",)
    assert preview.schema is not None
    assert preview.schema.primary_coordinates == ["readout_frequency"]
    assert preview.schema.primary_observables == ["signal"]
    assert [
        (
            variable.id,
            variable.dtype,
            variable.unit,
            variable.dims,
            variable.shape,
            variable.metadata,
        )
        for variable in preview.schema.variables
        if variable.role == "coordinate"
    ] == [
        (
            "readout_frequency",
            "float64",
            "GHz",
            ["point"],
            [2],
            {},
        )
    ]


def test_preview_contract_summarizes_record_axes() -> None:
    spec = typed_program(
        id="readout-iq",
        kind="readout.iq",
        point_source=_point_source(grid(index=[0])),
        records=[
            observable(
                "i0",
                unit="ratio",
                axes=[record_axis("shot", size=3, kind="shot", unit="count")],
            )
        ],
    )

    preview = preview_contract(spec, _parameters())

    assert preview.records[0].dims == ("point", "shot")
    assert preview.records[0].shape == (1, 3)
    assert preview.dataset_dimensions == {"point": 1, "shot": 3}
    assert preview.primary_observables == ("i0",)


def test_preview_contract_summarizes_compute_payload_boundary() -> None:
    def build_waveform() -> dict[str, object]:
        return {"kind": "waveform"}

    spec = typed_program(
        id="preview-waveform-boundary",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        state=[
            set_state_field(
                "drive-a",
                capability_id="play_waveforms",
                field_path="program",
                value=compute_result("build-waveform"),
            )
        ],
        compute_nodes=[
            TypedComputeNode(
                id=NodeId(local_id="build-waveform"),
                output_type=Scalar(Payload("waveform_bundle")),
                inputs={},
                fn=build_waveform,
            )
        ],
    )

    preview = preview_contract(spec, _parameters())

    assert preview.runtime.compute_node_count == 1
    assert preview.runtime.compute_step_count == 1
    assert preview.runtime.payload_count == 1
    assert len(preview.compute_steps) == 1
    step = preview.compute_steps[0]
    assert (
        step.point_index,
        step.node_id,
        step.schema_id,
        step.dependencies,
    ) == (0, "build-waveform", "waveform_bundle", {})
    assert step.payload_id is not None
    assert step.payload_id.startswith("build-waveform.payload.")
    assert preview.payloads[0].node_id == "build-waveform"
    assert preview.payloads[0].schema_id == "waveform_bundle"
    assert [
        (target.capability_id, target.field_path)
        for target in preview.payloads[0].state_fields
    ] == [("play_waveforms", "program")]
    assert preview.payloads[0].dependencies == {}


def test_preview_groups_shared_typed_compute_result() -> None:
    spec = typed_program(
        id="preview-shared-payload",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        state=[
            set_state_field(
                "drive-a",
                capability_id="play_waveforms",
                field_path="program",
                value=compute_result("build-waveform"),
            ),
            set_state_field(
                "drive-a",
                capability_id="play_waveforms",
                field_path="preview",
                value=compute_result("build-waveform"),
            ),
        ],
        compute_nodes=[
            TypedComputeNode(
                id=NodeId(local_id="build-waveform"),
                output_type=Scalar(Payload("waveform_bundle")),
                fn=lambda: {"kind": "waveform"},
            )
        ],
    )

    preview, problems = preview_result(spec, _parameters())

    assert problems == ()
    assert preview.compute_steps[0].payload_id is not None
    assert preview.compute_steps[0].payload_id.startswith("build-waveform.payload.")
    assert preview.compute_steps[0].schema_id == "waveform_bundle"
    assert len(preview.payloads) == 1
    assert preview.payloads[0].schema_id == "waveform_bundle"
    assert [
        (target.capability_id, target.field_path)
        for target in preview.payloads[0].state_fields
    ] == [
        ("play_waveforms", "preview"),
        ("play_waveforms", "program"),
    ]


def test_preview_contract_reports_unknown_compute_payload_nodes() -> None:
    spec = typed_program(
        id="preview-unknown-payload-node",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        state=[
            set_state_field(
                "drive-a",
                capability_id="play_waveforms",
                field_path="program",
                value=compute_result("missing-node"),
            )
        ],
        records=[],
    )

    preview, problems = preview_result(spec, _parameters())

    assert [problem.code for problem in problems] == ["compute_payload_unknown_node"]
    assert preview.compute_steps == ()


def test_preview_contract_records_are_durable() -> None:
    spec = typed_program(
        id="record-plan",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        records=[
            observable(
                "iq_trace",
                unit="V",
                resource="readout-a",
                axes=[record_axis("time", size=16, kind="time")],
            )
        ],
    )
    changed = spec.model_copy(
        update={
            "records": [observable("phase_trace", unit="rad", resource="readout-a")]
        },
        deep=True,
    )

    preview = preview_contract(spec, _parameters())
    changed_preview = preview_contract(changed, _parameters())

    assert [
        (
            record.id,
            record.kind,
            record.source,
            record.resource,
            record.unit,
            record.dtype,
            record.dims,
            record.shape,
        )
        for record in preview.records
    ] == [
        (
            "iq_trace",
            "observable",
            "instrument",
            "readout-a",
            "V",
            "float64",
            ("point", "time"),
            (1, 16),
        )
    ]
    assert changed_preview.records != preview.records
