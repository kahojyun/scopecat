from dataclasses import replace
from typing import Never, cast

from scopecat.compiler.linking.linked import (
    link_program as link_core_program,
)
from scopecat.compiler.linking.linked import (
    materialize_linked_points,
)
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.specialization import (
    ResidualScalar,
    specialize_scalar,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.value_expressions import TableValue
from scopecat.compiler.typed.parameter_overlays import (
    parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    LogicalResourceRequirement,
    TypedDomainExecution,
    ValueInput,
)
from scopecat.config.environment import build_config_environment
from scopecat.domain.program import DomainInputPort, DomainProgramDef
from scopecat.graph.relations.model import (
    CellValue,
    Row,
    parameter_lookup,
    point_col,
)
from scopecat.graph.relations.point_domain import (
    PointAxis,
    point_axis_values,
)
from scopecat.graph.table_values import ParameterTableSource
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String, Table, TableColumn
from tests.testkit.local_materialization import materialize_local_execution
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_state_properties,
)
from tests.testkit.parameter_fixtures import (
    PARAMETER_TYPES,
    READOUT_FREQUENCY_LOOKUP,
    parameters,
)
from tests.testkit.relation_plans import state_property
from tests.testkit.typed_program import (
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
        parameters={
            parameter_id: value_type
            for parameter_id, value_type in _PARAMETER_TYPES.items()
            if isinstance(value_type, Scalar)
        },
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
                interfaces=("test.readout/v1",),
            ),
        ),
        parameter_overlays=[_frequency_overlay(axis_id="frequency")],
        state=[
            state_property(
                "readout",
                interface_id="test.readout/v1",
                property_id="frequency",
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
            config_with_physical_resources({"readout-a": ("test.readout/v1",)})
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

    assert [
        target.value.root for _, _, target in materialized_state_properties(plan)
    ] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.2, unit="GHz"),
    ]
    assert [point.logical_id for point in plan.points] == [
        point.logical_id for point in without_overlay.points
    ]
    assert [
        row["frequency"] for row in environment.parameters.table_rows("readout_devices")
    ] == base_frequencies


def test_domain_compiler_table_is_point_scoped_after_overlay() -> None:
    points = _point_domain(
        (TableColumn("frequency", _FREQUENCY),),
        (
            (Quantity(value=5.9, unit="GHz"),),
            (Quantity(value=6.2, unit="GHz"),),
        ),
    )
    table_type = _PARAMETER_TYPES["readout_devices"]
    assert isinstance(table_type, Table)
    execution = TypedDomainExecution(
        id="compile",
        program=DomainProgramDef(
            id="consume-readout-table",
            dialect_id="test",
            dialect_version="1",
            body=object(),
            compiler_input_ports=(DomainInputPort("rows", table_type),),
        ),
        compiler_inputs={
            "rows": ValueInput(
                TableValue(
                    source=ParameterTableSource("readout_devices"),
                    value_type=table_type,
                )
            )
        },
    )
    spec = typed_program(
        id="whole-table-parameter-overlay",
        kind="readout.frequency_scan",
        point_domain=points,
        parameter_overlays=[_frequency_overlay(axis_id="frequency")],
        domain_execution=execution,
    )

    environment = replace(
        build_config_environment(config_with_physical_resources({})),
        parameters=parameters(),
    )
    linked_points = materialize_linked_points(link_core_program(spec, environment))
    [(input_id, bound_values)] = linked_points.bind_domain_inputs(
        execution.id,
        "compiler",
        ("rows",),
        (0, 1),
    )
    bound_tables = cast("tuple[tuple[Row, ...], ...]", bound_values)

    assert input_id == "rows"
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
