from scopecat.experiments import (
    ComputeNodeContext,
    ComputeNodeSpec,
    experiment,
    observable,
    record_axis,
    set_state,
    update_param_rows,
)
from scopecat.models.parameter import Quantity
from scopecat.relations import col, grid, linspace, param, table
from tests.support.experiment_preview import preview_contract, preview_result
from tests.support.parameter_fixtures import parameter_view as _parameter_view


def test_preview_contract_summarizes_points_state_and_records() -> None:
    spec = experiment(
        id="readout-frequency-calibration",
        kind="readout.frequency_scan",
        points=grid(
            readout=table("readout_devices").filter(col("enabled").eq(True)),
            readout_frequency=linspace(5.9, 6.0, 2, unit="GHz"),
        ),
        params=[
            update_param_rows(
                "readout_devices",
                key={"device_id": col("readout.device_id")},
                values={"frequency": col("readout_frequency")},
            )
        ],
        state=[
            set_state(
                col("readout.resource_id"),
                "pulse.frequency",
                param(
                    "readout_devices",
                    key={"device_id": col("readout.device_id")},
                    column="frequency",
                ),
            )
        ],
        records=[observable("signal", unit="ratio")],
    )

    preview = preview_contract(spec, _parameter_view())

    assert spec.schema_version == "scopecat.experiment_spec.v3"
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
    spec = experiment(
        id="readout-iq",
        kind="readout.iq",
        points=grid(index=[0]),
        records=[
            observable(
                "i0",
                unit="ratio",
                axes=[record_axis("shot", size=3, kind="shot", unit="count")],
            )
        ],
    )

    preview = preview_contract(spec, _parameter_view())

    assert preview.records[0].dims == ("point", "shot")
    assert preview.records[0].shape == (1, 3)
    assert preview.dataset_dimensions == {"point": 1, "shot": 3}
    assert preview.primary_observables == ("i0",)


def test_preview_contract_carries_parameter_view_diagnostics() -> None:
    params = _parameter_view().model_copy(
        update={
            "diagnostics": [
                {
                    "severity": "info",
                    "code": "derived_table_replaces_source",
                    "message": "derived table replaces a source table",
                    "path": "parameter_view.tables.readout_devices",
                }
            ]
        },
        deep=True,
    )
    spec = experiment(
        id="diagnostic-plan",
        kind="diagnostic",
        points=grid(frequency=linspace(5.9, 6.0, 1, unit="GHz")),
        records=[],
    )

    _preview, diagnostics = preview_result(spec, params)

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "derived_table_replaces_source"
    ]


def test_preview_contract_summarizes_compute_payload_boundary() -> None:
    def build_waveform(ctx: ComputeNodeContext) -> dict[str, object]:
        return {"point_index": ctx.point_index}

    spec = experiment(
        id="preview-waveform-boundary",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                {
                    "kind": "compute_result",
                    "node_id": "build-waveform",
                    "payload_kind": "waveform_bundle",
                },
            )
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
                    inputs={},
                    fn=build_waveform,
                )
            ]
        }
    )

    preview = preview_contract(spec, _parameter_view())

    assert preview.runtime.compute_node_count == 1
    assert preview.runtime.compute_step_count == 1
    assert preview.runtime.payload_count == 1
    assert [
        (
            step.point_index,
            step.node_id,
            step.payload_id,
            step.payload_kind,
            step.dependencies,
        )
        for step in preview.compute_steps
    ] == [
        (
            0,
            "build-waveform",
            "build-waveform.payload.point-0",
            "waveform_bundle",
            {},
        )
    ]
    assert preview.payloads[0].node_id == "build-waveform"
    assert preview.payloads[0].kind == "waveform_bundle"
    assert preview.payloads[0].state_fields == ("play_waveforms.program",)
    assert preview.payloads[0].dependencies == {}


def test_preview_contract_records_are_durable() -> None:
    spec = experiment(
        id="record-plan",
        kind="diagnostic",
        points=grid(index=[0]),
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

    preview = preview_contract(spec, _parameter_view())
    changed_preview = preview_contract(changed, _parameter_view())

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
