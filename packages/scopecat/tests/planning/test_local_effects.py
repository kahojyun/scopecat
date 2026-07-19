import pytest

from scopecat.compiler.relations.model import (
    RelationExpr,
    col,
    grid,
    linspace,
    param,
    point_col,
    table,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
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
    ResourceRouteIntent,
    TypedComputeNode,
    TypedComputeOutput,
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
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.resource_identity import (
    PhysicalResourceId,
    logical_resource_port_id,
)
from scopecat.kernel.state import PayloadRef
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Payload, Scalar, String
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
    point_domain as verified_point_domain,
)
from tests.testkit.relation_plans import (
    state_field as set_state_field,
)
from tests.testkit.typed_program import (
    compute_result,
    instrument_product_producer,
    observable_product,
    overlay_parameter_cell,
    typed_program,
)


def _point_domain(expr: RelationExpr) -> PointDomain:
    return verified_point_domain(
        expr,
        bindings=RelationTypeBindings(parameters=PARAMETER_TYPES),
    )


def test_materialized_effects_contract_summarizes_points_and_state() -> None:
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
        physical_resource_id=PhysicalResourceId("readout-a"),
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

    test_config = config_with_physical_resources(
        {"readout-a": ("pulse",), "readout-b": ("pulse",)}
    )
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


def test_materialized_effects_contract_rejects_unknown_compute_payload_nodes() -> None:
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

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(
            spec,
            _parameters(),
            config=config_with_physical_resources({"drive-a": ("play_waveforms",)}),
        )

    assert [problem.code for problem in failure.value.problems] == [
        "compute_payload_unknown_output"
    ]


def test_materialized_effects_selects_local_product_realization() -> None:
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
    config = config_with_physical_resources({"readout-a": ()})
    preview = materialized_effects_contract(spec, _parameters(), config=config)
    [operation] = operations_of_type(preview, CollectOperation, point_index=0)
    [binding] = operation.result_bindings
    assert operation.instrument_id == "readout-a"
    assert binding.product_use_id == product_use.id
