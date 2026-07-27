from dataclasses import replace
from typing import Never, cast

from scopecat.compiler.linking.linked import link_program as link_core_program
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.specialization import (
    ResidualScalar,
    specialize_scalar,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.compiler.typed.parameter_overlays import (
    parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    LogicalResourceRequirement,
    TypedComputeNode,
    ValueInput,
)
from scopecat.compiler.typed.program import set_state_field as set_typed_state_field
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import BoundInput, ComputeOperation
from scopecat.graph.relations.model import (
    CellValue,
    Row,
    parameter_lookup,
    point_col,
    table,
)
from scopecat.graph.relations.point_domain import (
    PointAxis,
    point_axis_values,
)
from scopecat.graph.values import ComputeOutput, OperationId, operation_result_id
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Payload, Scalar, String, TableColumn
from scopecat.kernel.value_types import Quantity as QuantityType
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_state_fields,
)
from tests.testkit.parameter_fixtures import (
    PARAMETER_TYPES,
    READOUT_FREQUENCY_LOOKUP,
    parameters,
)
from tests.testkit.relation_plans import state_field, table_value_expr
from tests.testkit.typed_program import (
    compute_result,
    link_program,
    overlay_parameter_cell,
    typed_program,
)

_PARAMETER_TYPES = PARAMETER_TYPES
_DEVICE_ID = Scalar(String())
_FREQUENCY = Scalar(QuantityType(dimension="frequency"))


def _point_domain(
    columns: tuple[TableColumn, ...],
    rows: tuple[tuple[CellValue, ...], ...],
) -> PointDomain:
    factors: list[PointAxis[Never]] = []
    for index, column in enumerate(columns):
        values: list[CellValue] = []
        for row in rows:
            if row[index] not in values:
                values.append(row[index])
        factors.append(point_axis_values(column.id, column.value_type, tuple(values)))
    return PointDomain(axes=tuple(factors))


def _point_bindings(points: PointDomain) -> RelationTypeBindings:
    return RelationTypeBindings(
        parameters=_PARAMETER_TYPES,
        point_row=RowType.from_table(points.value_type),
    )


def _frequency_overlay(*, axis_id: str):
    return overlay_parameter_cell(
        "readout_devices",
        row_index=0,
        key={"device_id": "r0"},
        column_id="frequency",
        axis_id=axis_id,
    )


def test_point_parameter_overlay_replaces_only_one_existing_cell() -> None:
    points = _point_domain(
        (
            TableColumn("device_id", _DEVICE_ID),
            TableColumn("frequency", _FREQUENCY),
        ),
        (
            ("r0", Quantity(value=5_900, unit="MHz")),
            ("r0", Quantity(value=6_200, unit="MHz")),
        ),
    )
    point_bindings = _point_bindings(points)
    spec = typed_program(
        id="readout-frequency-overlay",
        kind="readout.frequency_scan",
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("readout"),
                capabilities=("readout",),
            ),
        ),
        parameter_overlays=[_frequency_overlay(axis_id="frequency")],
        state=[
            state_field(
                "readout",
                capability_id="readout",
                field_path="frequency",
                value=parameter_lookup(
                    READOUT_FREQUENCY_LOOKUP,
                    key={"device_id": point_col("device_id")},
                ),
                bindings=point_bindings,
            )
        ],
    )

    environment = replace(
        build_config_environment(
            config_with_physical_resources({"readout-a": ("readout",)})
        ),
        parameters=parameters(),
    )
    base_frequencies = [
        row["frequency"] for row in environment.parameters.table_rows("readout_devices")
    ]
    plan = materialize_local_execution(link_program(spec, environment))
    without_overlay = materialize_local_execution(
        link_program(replace(spec, parameter_overlays=()), environment)
    )

    assert [field.value.root for _, _, field in materialized_state_fields(plan)] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.2, unit="GHz"),
    ]
    assert [point.logical_id for point in plan.points] == [
        point.logical_id for point in without_overlay.points
    ]
    assert [
        row["frequency"] for row in environment.parameters.table_rows("readout_devices")
    ] == base_frequencies


def test_whole_parameter_table_compute_is_point_scoped_after_overlay() -> None:
    def summarize_rows(*, rows: tuple[Row, ...]) -> dict[str, int]:
        return {"row_count": len(rows)}

    points = _point_domain(
        (TableColumn("frequency", _FREQUENCY),),
        (
            (Quantity(value=5.9, unit="GHz"),),
            (Quantity(value=6.2, unit="GHz"),),
        ),
    )
    bindings = _point_bindings(points)
    operation_id = OperationId(SymbolId(local_id="consume-readout-table"))
    sink = logical_resource_port_id("sink")
    spec = typed_program(
        id="whole-table-parameter-overlay",
        kind="readout.frequency_scan",
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=sink,
                capabilities=("consume_rows",),
            ),
        ),
        parameter_overlays=[_frequency_overlay(axis_id="frequency")],
        compute_nodes=[
            TypedComputeNode(
                id=operation_id,
                implementation=LocalPythonImplementation(
                    id=ImplementationId("python.consume-readout-table.v1"),
                    kernel=summarize_rows,
                ),
                inputs={
                    "rows": ValueInput(
                        value=table_value_expr(
                            table("readout_devices"),
                            expected_type=_PARAMETER_TYPES["readout_devices"],
                            bindings=bindings,
                        )
                    )
                },
                result=ComputeOutput(
                    id=operation_result_id(operation_id),
                    value_type=Scalar(Payload("row_summary")),
                ),
            )
        ],
        state=[
            set_typed_state_field(
                resource_port_id=sink,
                capability_id="consume_rows",
                field_path="count",
                value=compute_result(operation_id),
            )
        ],
    )

    environment = replace(
        build_config_environment(
            config_with_physical_resources({"sink-a": ("consume_rows",)})
        ),
        parameters=parameters(),
    )
    plan = materialize_local_execution(link_core_program(spec, environment))

    compute_effects = [
        effect
        for effect in plan.effects
        if isinstance(effect.operation, ComputeOperation)
    ]
    assert [effect.point_index for effect in compute_effects] == [0, 1]

    bound_tables: list[tuple[Row, ...]] = []
    for point in plan.points:
        [operation] = operations_of_type(
            plan,
            ComputeOperation,
            point_index=point.ordinal,
        )
        rows_input = operation.inputs["rows"]
        assert isinstance(rows_input, BoundInput)
        assert isinstance(rows_input.value, tuple)
        bound_tables.append(cast("tuple[Row, ...]", rows_input.value))

    assert [len(rows) for rows in bound_tables] == [2, 2]
    assert [
        next(row["frequency"] for row in rows if row["device_id"] == "r0")
        for rows in bound_tables
    ] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.2, unit="GHz"),
    ]


def test_point_parameter_overlay_residualizes_parameter_lookup() -> None:
    overlay = _frequency_overlay(axis_id="frequency")
    parameters_for_run = parameters()
    cells = parameter_cell_bindings((overlay,))

    result = specialize_scalar(
        parameter_lookup(
            READOUT_FREQUENCY_LOOKUP,
            key={"device_id": "r0"},
        ),
        known=EvalContext(params=parameters_for_run),
        parameter_cells=cells,
    )

    assert isinstance(result, ResidualScalar)
    assert result.expression == point_col("frequency")
