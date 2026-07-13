from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    ResourceRouteIntent,
    TypedComputeNode,
    TypedComputeOutput,
    compute_result,
    instrument_product_producer,
    observable_product,
    overlay_parameter_cell,
    product_axis,
    record_product,
    typed_program,
)
from scopecat._compiler.program import (
    set_state_field as set_typed_state_field,
)
from scopecat._operation_contract import LOCAL_OPAQUE_OPERATION_CONTRACT
from scopecat._relation_verification import RelationTypeBindings, RowType
from scopecat._relations import (
    RelationExpr,
    col,
    grid,
    linspace,
    param,
    point_col,
    table,
)
from scopecat._resource_identity import logical_resource_port_id, physical_resource_id
from scopecat._semantic_graph import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    operation_result_id,
)
from scopecat._symbols import SymbolId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.models.parameter import Quantity
from scopecat.value_types import Payload, Scalar, String
from scopecat.value_types import Quantity as QuantityType
from tests.support.experiment_preview import (
    config_with_physical_resources,
    preview_contract,
    preview_result,
)
from tests.support.parameter_fixtures import (
    PARAMETER_TYPES,
    READOUT_FREQUENCY_LOOKUP,
)
from tests.support.parameter_fixtures import (
    parameters as _parameters,
)
from tests.support.relation_plans import (
    point_domain as verified_point_domain,
)
from tests.support.relation_plans import (
    state_field as set_state_field,
)


def _point_domain(expr: RelationExpr) -> PointDomain:
    return verified_point_domain(
        expr,
        bindings=RelationTypeBindings(parameters=PARAMETER_TYPES),
    )


def test_preview_contract_summarizes_points_state_and_records() -> None:
    points = _point_domain(
        grid(
            readout=table("readout_devices").filter(col("enabled").eq(True)),
            readout_frequency=linspace(5.9, 6.0, 2, unit="GHz"),
        )
    )
    bindings = RelationTypeBindings(
        parameters=PARAMETER_TYPES,
        parameter_lookups=(READOUT_FREQUENCY_LOOKUP,),
        point_row=RowType.from_table(points.value_type),
    )
    product = observable_product(
        "signal",
        unit="ratio",
    )
    producer = instrument_product_producer(
        product,
        physical_resource_id=physical_resource_id("readout-a"),
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="readout-frequency-calibration",
        kind="readout.frequency_scan",
        point_domain=points,
        parameter_overlays=[
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": point_col("readout.device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=point_col("readout_frequency"),
                value_type=Scalar(QuantityType(unit="GHz")),
                bindings=bindings,
            )
        ],
        state=[
            set_state_field(
                point_col("readout.resource_id"),
                capability_id="pulse",
                field_path="frequency",
                value=param(
                    "readout_devices",
                    key={"device_id": point_col("readout.device_id")},
                    column="frequency",
                ),
                bindings=bindings,
            )
        ],
        product_defs=[product],
        instrument_product_producers=[producer],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    preview = preview_contract(
        spec,
        _parameters(),
        config=config_with_physical_resources(
            {"readout-a": ("pulse",), "readout-b": ("pulse",)}
        ),
    )

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
            record.producer_kind,
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
    product = observable_product(
        "i0",
        unit="ratio",
        axes=[product_axis("shot", size=3, kind="shot", unit="count")],
    )
    producer = instrument_product_producer(product)
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="readout-iq",
        kind="readout.iq",
        point_domain=_point_domain(grid(index=[0])),
        product_defs=[product],
        instrument_product_producers=[producer],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    preview = preview_contract(spec, _parameters())

    assert preview.records[0].dims == ("point", "shot")
    assert preview.records[0].shape == (1, 3)
    assert preview.dataset_dimensions == {"point": 1, "shot": 3}
    assert preview.primary_observables == ("i0",)


def test_preview_contract_summarizes_compute_payload_boundary() -> None:
    def build_waveform() -> dict[str, object]:
        return {"kind": "waveform"}

    operation_id = OperationId(SymbolId(local_id="build-waveform"))
    result_id = operation_result_id(operation_id)
    drive = logical_resource_port_id("drive")
    spec = typed_program(
        id="preview-waveform-boundary",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        state=[
            set_typed_state_field(
                resource_port_id=drive,
                capability_id="play_waveforms",
                field_path="program",
                value=compute_result("build-waveform"),
            )
        ],
        route_intents=(
            ResourceRouteIntent(
                port_id=drive,
                capabilities=("play_waveforms",),
            ),
        ),
        compute_nodes=[
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                result=TypedComputeOutput(
                    id=result_id,
                    value_type=Scalar(Payload("waveform_bundle")),
                    availability=ValueAvailability(
                        ValueStage.EXECUTE,
                        ValueRate.POINT,
                    ),
                ),
                inputs={},
            )
        ],
        implementation_catalog=ImplementationCatalog(
            local_python=(
                LocalPythonImplementation(
                    id=ImplementationId("python.build-waveform.v1"),
                    operation_id=operation_id,
                    operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    kernel=build_waveform,
                ),
            )
        ),
    )

    preview = preview_contract(
        spec,
        _parameters(),
        config=config_with_physical_resources({"drive-a": ("play_waveforms",)}),
    )

    assert preview.runtime.compute_operation_count == 1
    assert preview.runtime.compute_step_count == 1
    assert preview.runtime.payload_count == 1
    assert len(preview.compute_steps) == 1
    step = preview.compute_steps[0]
    assert (
        step.point_index,
        step.semantic_operation_id,
        step.schema_id,
        step.dependencies,
    ) == (0, "build-waveform", "waveform_bundle", {})
    assert step.payload_id is not None
    assert step.payload_id.startswith(f"{result_id.qualified_name}.payload.")
    assert preview.payloads[0].semantic_operation_id == "build-waveform"
    assert preview.payloads[0].schema_id == "waveform_bundle"
    assert [
        (target.resource_port_id, target.capability_id, target.field_path)
        for target in preview.payloads[0].state_fields
    ] == [("drive", "play_waveforms", "program")]
    assert preview.payloads[0].dependencies == {}


def test_preview_groups_shared_typed_compute_result() -> None:
    operation_id = OperationId(SymbolId(local_id="build-waveform"))
    result_id = operation_result_id(operation_id)

    def build_waveform() -> dict[str, object]:
        return {"kind": "waveform"}

    spec = typed_program(
        id="preview-shared-payload",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
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
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                result=TypedComputeOutput(
                    id=result_id,
                    value_type=Scalar(Payload("waveform_bundle")),
                    availability=ValueAvailability(
                        ValueStage.EXECUTE,
                        ValueRate.POINT,
                    ),
                ),
            )
        ],
        implementation_catalog=ImplementationCatalog(
            local_python=(
                LocalPythonImplementation(
                    id=ImplementationId("python.build-waveform.v1"),
                    operation_id=operation_id,
                    operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    kernel=build_waveform,
                ),
            )
        ),
    )

    preview, problems = preview_result(
        spec,
        _parameters(),
        config=config_with_physical_resources({"drive-a": ("play_waveforms",)}),
    )

    assert problems == ()
    assert preview.compute_steps[0].payload_id is not None
    assert preview.compute_steps[0].payload_id.startswith(
        f"{result_id.qualified_name}.payload."
    )
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
        point_domain=_point_domain(grid(index=[0])),
        state=[
            set_state_field(
                "drive-a",
                capability_id="play_waveforms",
                field_path="program",
                value=compute_result("missing-node"),
            )
        ],
    )

    preview, problems = preview_result(
        spec,
        _parameters(),
        config=config_with_physical_resources({"drive-a": ("play_waveforms",)}),
    )

    assert [problem.code for problem in problems] == ["compute_payload_unknown_output"]
    assert preview.compute_steps == ()


def test_preview_contract_records_are_durable() -> None:
    product = observable_product(
        "iq_trace",
        unit="V",
        axes=[product_axis("time", size=16, kind="time")],
    )
    producer = instrument_product_producer(
        product,
        physical_resource_id="readout-a",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="record-plan",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        product_defs=[product],
        instrument_product_producers=[producer],
        product_uses=[product_use],
        record_uses=[record_use],
    )
    changed_product = observable_product(
        "phase_trace",
        unit="rad",
    )
    changed_producer = instrument_product_producer(
        changed_product,
        physical_resource_id="readout-a",
    )
    changed_product_use, changed_record_use = record_product(changed_product)
    changed = spec.model_copy(
        update={
            "product_defs": (changed_product,),
            "instrument_product_producers": (changed_producer,),
            "product_uses": (changed_product_use,),
            "record_uses": (changed_record_use,),
        },
        deep=True,
    )

    config = config_with_physical_resources({"readout-a": ()})
    preview = preview_contract(spec, _parameters(), config=config)
    changed_preview = preview_contract(changed, _parameters(), config=config)

    assert [
        (
            record.id,
            record.kind,
            record.producer_kind,
            record.resource_port_id,
            record.physical_resource_id,
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
            None,
            "readout-a",
            "V",
            "float64",
            ("point", "time"),
            (1, 16),
        )
    ]
    assert changed_preview.records != preview.records
