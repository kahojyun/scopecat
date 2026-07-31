from __future__ import annotations

from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    BoundProgramFacts,
    TypedComputeNode,
    TypedDomainExecution,
    set_state_property,
)
from scopecat.compiler.typed.specialization import (
    specialize_bound_facts,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.compiler.typed.values import TableValue
from scopecat.domain.program import DomainInputPort, DomainProgramDef
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Float,
    Int,
    Quantity,
    Scalar,
    Table,
    TableColumn,
)
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    LiteralScalarExpr,
    PointColumnScalarExpr,
    param,
    parameter_lookup,
)
from scopecat.program.logical import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.program.point_domain import (
    PointAxis,
    PointAxisLinear,
    point_axis_linear,
    point_axis_values,
)
from scopecat.program.table_values import ParameterTableSource
from scopecat.program.value_graph import (
    ComputeOutput,
    OperationId,
    operation_result_id,
)
from tests.testkit.parameter_fixtures import (
    READOUT_FREQUENCY_LOOKUP,
    parameters,
)
from tests.testkit.relation_plans import (
    scalar_value_expr,
)


def test_bound_fact_specialization_folds_scalar_inputs_across_effect_kinds() -> None:
    value_type = Scalar(Float())
    config_value = scalar_value_expr(
        param("gain", value_type),
        bindings=RelationTypeBindings(parameters={"gain": value_type}),
        expected_type=value_type,
    )
    domain = TypedDomainExecution(
        id="domain",
        program=DomainProgramDef(
            id="program",
            dialect_id="tests.specialization",
            dialect_version="1",
            body=(),
            input_ports=(DomainInputPort("gain", value_type),),
        ),
        inputs={"gain": config_value},
    )
    state = set_state_property(
        resource_port_id=logical_resource_port_id("drive"),
        interface_id="drive",
        property_id="gain",
        value=config_value,
    )
    specialized = specialize_bound_facts(
        BoundProgramFacts(
            point_domain=PointDomain(axes=()),
            effects=(state, domain),
        ),
        parameters=ParameterRelationData(scalars={"gain": 2.5}),
    )

    specialized_state = specialized.effects[0]
    assert isinstance(specialized_state, SetStateSpec)
    state_value = specialized_state.value_use
    assert isinstance(state_value, LiteralScalarExpr)
    assert state_value.value == 2.5
    assert state_value.value_type == value_type
    specialized_domain = specialized.effects[1]
    assert isinstance(specialized_domain, TypedDomainExecution)
    domain_input = specialized_domain.inputs["gain"]
    assert isinstance(domain_input, LiteralScalarExpr)
    assert domain_input.value == 2.5
    assert domain_input.value_type == value_type


def test_bound_fact_specialization_preserves_direct_parameter_table_sources() -> None:
    integer = Scalar(Int())
    table_type = Table((TableColumn("x", integer),))
    source = ParameterTableSource("rows")
    value = TableValue(source, table_type)
    domain = TypedDomainExecution(
        id="domain",
        program=DomainProgramDef(
            id="program",
            dialect_id="tests.specialization",
            dialect_version="1",
            body=(),
            compiler_input_ports=(DomainInputPort("rows", table_type),),
        ),
        compiler_inputs={"rows": value},
    )
    specialized = specialize_bound_facts(
        BoundProgramFacts(
            point_domain=PointDomain(axes=()),
            effects=(domain,),
        ),
        parameters=ParameterRelationData(tables={"rows": [{"x": 3}, {"x": 4}]}),
    )

    [specialized_domain] = specialized.effects
    assert isinstance(specialized_domain, TypedDomainExecution)
    specialized_value = specialized_domain.compiler_inputs["rows"]
    assert isinstance(specialized_value, TableValue)
    assert specialized_value.source is source
    assert specialized_value.value_type == table_type


def test_bound_fact_specialization_prunes_dead_compute_nodes() -> None:
    value_type = Scalar(Float())

    def compute(
        name: str, upstream: TypedComputeNode | None = None
    ) -> TypedComputeNode:
        operation_id = OperationId(SymbolId(local_id=name))
        return TypedComputeNode(
            id=operation_id,
            implementation=LocalPythonImplementation(
                id=ImplementationId(f"python.{name}"),
                kernel=lambda: None,
            ),
            result=ComputeOutput(
                id=operation_result_id(operation_id),
                value_type=value_type,
            ),
            input_types=({} if upstream is None else {"upstream": value_type}),
            inputs=(
                {}
                if upstream is None
                else {
                    "upstream": ComputeResultScalarExpr(
                        value_id=upstream.result.id,
                        value_type=value_type,
                    )
                }
            ),
        )

    upstream = compute("upstream")
    live = compute("live", upstream)
    dead = compute("dead")
    state = set_state_property(
        resource_port_id=logical_resource_port_id("drive"),
        interface_id="drive",
        property_id="payload",
        value=ComputeResultScalarExpr(
            value_id=live.result.id,
            value_type=value_type,
        ),
    )

    specialized = specialize_bound_facts(
        BoundProgramFacts(
            point_domain=PointDomain(axes=()),
            compute_nodes=(upstream, live, dead),
            effects=(state,),
        ),
        parameters=ParameterRelationData(),
    )

    assert tuple(node.id for node in specialized.compute_nodes) == (
        upstream.id,
        live.id,
    )


def test_bound_fact_specialization_preserves_exact_empty_point_composition() -> None:
    integer = Scalar(Int())

    specialized = specialize_bound_facts(
        BoundProgramFacts(
            point_domain=PointDomain(
                axes=(
                    point_axis_values("x", integer, (1,)),
                    point_axis_values("y", integer, ()),
                ),
            ),
        ),
        parameters=ParameterRelationData(),
    )

    column_ids = tuple(
        column.id for column in specialized.point_domain.value_type.columns
    )
    assert column_ids == ("x", "y")


def test_point_domain_center_reads_base_parameter_before_point_overlay() -> None:
    frequency = Scalar(Quantity(unit="GHz"))
    point_row = RowType((TableColumn("frequency", frequency),))
    point_bindings = RelationTypeBindings(
        point_row=point_row,
    )
    center = scalar_value_expr(
        parameter_lookup(
            READOUT_FREQUENCY_LOOKUP,
            key={"device_id": "r0"},
        ),
        bindings=RelationTypeBindings(),
        expected_type=frequency,
    )
    overlaid_lookup = scalar_value_expr(
        parameter_lookup(
            READOUT_FREQUENCY_LOOKUP,
            key={"device_id": "r0"},
        ),
        bindings=point_bindings,
        expected_type=frequency,
    )
    overlay = PointParameterOverlay(
        table_id="readout_devices",
        row_index=0,
        key={"device_id": "r0"},
        column_id="frequency",
        axis_id="frequency",
        value_type=frequency,
    )
    domain = TypedDomainExecution(
        id="domain",
        program=DomainProgramDef(
            id="program",
            dialect_id="tests.specialization",
            dialect_version="1",
            body=(),
            input_ports=(DomainInputPort("frequency", frequency),),
        ),
        inputs={"frequency": overlaid_lookup},
    )

    specialized = specialize_bound_facts(
        BoundProgramFacts(
            point_domain=PointDomain(
                axes=(
                    point_axis_linear(
                        "frequency",
                        frequency,
                        center,
                        QuantityValue(value=0.2, unit="GHz"),
                        3,
                    ),
                )
            ),
            parameter_overlays=(overlay,),
            effects=(domain,),
        ),
        parameters=parameters(),
    )

    [axis] = specialized.point_domain.axes
    assert isinstance(axis, PointAxis)
    assert isinstance(axis.source, PointAxisLinear)
    center_expression = axis.source.center
    assert isinstance(center_expression, LiteralScalarExpr)
    assert center_expression.value == QuantityValue(value=5.95, unit="GHz")
    assert center_expression.value_type == frequency

    [specialized_domain] = specialized.effects
    assert isinstance(specialized_domain, TypedDomainExecution)
    input_expression = specialized_domain.inputs["frequency"]
    assert isinstance(input_expression, PointColumnScalarExpr)
    assert input_expression.name == "frequency"
    assert input_expression.value_type == frequency
