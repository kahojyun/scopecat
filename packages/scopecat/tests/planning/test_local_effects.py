from scopecat.compiler.relations.model import (
    CellValue,
    parameter_lookup,
    point_col,
)
from scopecat.compiler.relations.point_domain import point_axis_values
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.compute_result import ComputeOutput
from scopecat.compiler.semantic.model import (
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    LogicalResourceRequirement,
    TypedComputeNode,
    product_axis,
    record_product,
)
from scopecat.compiler.typed.program import (
    set_state_field as set_typed_state_field,
)
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
)
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.state import PayloadRef
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Int, Payload, Scalar, String
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.records.parameter import Quantity
from tests.testkit.local_materialization import operations_of_type
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_effects_contract,
    materialized_state_fields,
    measurement_projection_contract,
)
from tests.testkit.parameter_fixtures import (
    PARAMETER_TYPES,
    READOUT_FREQUENCY_LOOKUP,
)
from tests.testkit.parameter_fixtures import (
    parameters as _parameters,
)
from tests.testkit.relation_plans import (
    state_field as set_state_field,
)
from tests.testkit.typed_program import (
    compute_result,
    instrument_acquisition,
    observable_product,
    overlay_parameter_cell,
    typed_program,
)


def _point_domain(
    column_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointDomain:
    return PointDomain(
        root=point_axis_values(column_id, value_type, values),
    )


def test_materialized_effects_contract_summarizes_points_and_state() -> None:
    points = _point_domain(
        "readout_frequency",
        Scalar(QuantityType(unit="GHz")),
        (
            Quantity(value=5.9, unit="GHz"),
            Quantity(value=6.0, unit="GHz"),
        ),
    )
    bindings = RelationTypeBindings(
        parameters=PARAMETER_TYPES,
        point_row=RowType.from_table(points.value_type),
    )
    product = observable_product(
        "signal",
        unit="ratio",
    )
    acquisition = instrument_acquisition(
        product,
        resource_port_id="readout",
        capability="pulse",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="readout-frequency-calibration",
        kind="readout.frequency_scan",
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("readout"),
                capabilities=("pulse",),
            ),
        ),
        parameter_overlays=[
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": "r0"},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=point_col("readout_frequency"),
                value_type=Scalar(QuantityType(unit="GHz")),
                bindings=bindings,
            )
        ],
        state=[
            set_state_field(
                "readout",
                capability_id="pulse",
                field_path="frequency",
                value=parameter_lookup(
                    READOUT_FREQUENCY_LOOKUP,
                    key={"device_id": "r0"},
                ),
                bindings=bindings,
            )
        ],
        product_defs=[product],
        instrument_acquisitions=[acquisition],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    test_config = config_with_physical_resources({"readout-a": ("pulse",)})
    preview = materialized_effects_contract(
        spec,
        _parameters(),
        config=test_config,
    )
    projection = measurement_projection_contract(
        spec,
        _parameters(),
        config=test_config,
    )

    assert len(preview.points) == 2
    assert projection.coordinate_ids == ("readout_frequency",)
    assert [point.coordinates["readout_frequency"] for point in preview.points] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
    assert [field.value.root for _, _, field in materialized_state_fields(preview)] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]


def test_materialized_effects_contract_summarizes_compute_payload_boundary() -> None:
    def build_waveform() -> dict[str, object]:
        return {"kind": "waveform"}

    operation_id = OperationId(SymbolId(local_id="build-waveform"))
    result_id = operation_result_id(operation_id)
    drive = logical_resource_port_id("drive")
    spec = typed_program(
        id="preview-waveform-boundary",
        kind="problem",
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
        state=[
            set_typed_state_field(
                resource_port_id=drive,
                capability_id="play_waveforms",
                field_path="program",
                value=compute_result("build-waveform"),
            )
        ],
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=drive,
                capabilities=("play_waveforms",),
            ),
        ),
        compute_nodes=[
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                implementation=LocalPythonImplementation(
                    id=ImplementationId("python.build-waveform.v1"),
                    kernel=build_waveform,
                ),
                result=ComputeOutput(
                    id=result_id,
                    value_type=Scalar(Payload("waveform_bundle")),
                ),
                inputs={},
            )
        ],
    )

    preview = materialized_effects_contract(
        spec,
        _parameters(),
        config=config_with_physical_resources({"drive-a": ("play_waveforms",)}),
    )

    [step] = preview.preamble_operations
    assert step.payload_slot is not None
    assert (
        preview.points[0].ordinal,
        step.semantic_operation_id,
        step.payload_slot.schema_id,
        dict(step.dependencies),
    ) == (0, "build-waveform", "waveform_bundle", {})
    assert step.payload_slot.id.startswith(f"{result_id.qualified_name}.payload.")
    assert [
        (
            state.instrument_id,
            field.capability_id,
            field.field_path,
        )
        for state in operations_of_type(preview, ApplyStateOperation, point_index=0)
        for field in state.targets
        if isinstance(field.value.root, PayloadRef)
    ] == [("drive-a", "play_waveforms", "program")]


def test_materialized_effects_groups_shared_typed_compute_result() -> None:
    operation_id = OperationId(SymbolId(local_id="build-waveform"))
    result_id = operation_result_id(operation_id)

    def build_waveform() -> dict[str, object]:
        return {"kind": "waveform"}

    spec = typed_program(
        id="preview-shared-payload",
        kind="problem",
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("drive-a"),
                capabilities=("play_waveforms",),
            ),
        ),
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
                implementation=LocalPythonImplementation(
                    id=ImplementationId("python.build-waveform.v1"),
                    kernel=build_waveform,
                ),
                result=ComputeOutput(
                    id=result_id,
                    value_type=Scalar(Payload("waveform_bundle")),
                ),
            )
        ],
    )

    preview = materialized_effects_contract(
        spec,
        _parameters(),
        config=config_with_physical_resources({"drive-a": ("play_waveforms",)}),
    )

    [step] = preview.preamble_operations
    assert step.payload_slot is not None
    assert step.payload_slot.id.startswith(f"{result_id.qualified_name}.payload.")
    assert step.payload_slot.schema_id == "waveform_bundle"
    assert [
        (field.capability_id, field.field_path)
        for state in operations_of_type(preview, ApplyStateOperation, point_index=0)
        for field in state.targets
        if isinstance(field.value.root, PayloadRef)
    ] == [
        ("play_waveforms", "program"),
        ("play_waveforms", "preview"),
    ]


def test_materialized_effects_binds_acquisition_to_its_logical_port() -> None:
    product = observable_product(
        "iq_trace",
        unit="V",
        axes=[product_axis("time", size=16, kind="time")],
    )
    acquisition = instrument_acquisition(
        product,
        resource_port_id="readout",
        capability="measure_iq",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="record-plan",
        kind="problem",
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("readout"),
                capabilities=("measure_iq",),
            ),
        ),
        product_defs=[product],
        instrument_acquisitions=[acquisition],
        product_uses=[product_use],
        record_uses=[record_use],
    )
    config = config_with_physical_resources({"readout-a": ("measure_iq",)})
    preview = materialized_effects_contract(spec, _parameters(), config=config)
    [operation] = operations_of_type(preview, CollectOperation, point_index=0)
    [binding] = operation.result_bindings
    assert operation.instrument_id == "readout-a"
    assert binding.product_use_ids == (product_use.id,)
