from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat._resource_identity import logical_resource_port_id
from scopecat._semantic_graph import RouteValueSource
from scopecat._symbols import SymbolId
from scopecat.authoring._elaboration import elaborate_module
from scopecat.authoring._graph_validation import verify_assembly_graph
from scopecat.authoring._resolution import resolve_experiment
from scopecat.errors import CheckFailed
from scopecat.problems import model_location
from tests.support.authoring import load_config


def _resource_module() -> sc.ExperimentModule:
    frequency = sc.Quantity(value=5.0, unit="GHz")
    route = sc.route("drive.v1", capabilities=("set.frequency",))
    program = sc.compute(
        "program",
        fn=lambda *, route: {"route": route},
        inputs={"route": route},
        output_type=sc.ScalarType(sc.PayloadType("test.resource-program")),
    )
    return (
        sc.module("test.resources.child")
        .resource("drive.v1", requires=("set.frequency",))
        .bind_field(
            "drive.v1",
            capability="set.frequency",
            field="value.path",
            value=frequency,
        )
        .computes(program)
        .product("signal", resource="drive.v1")
        .build()
    )


def test_explicit_instances_own_independent_resource_ports(tmp_path: Path) -> None:
    child = _resource_module()
    left = child.instantiate("left.arm")
    right = child.instantiate("right.arm")
    root = sc.module("test.resources.root").use(left, right).build()

    assembly = elaborate_module(root)
    verified = verify_assembly_graph(assembly)

    assert tuple(verified.resource_ports) == (
        logical_resource_port_id(SymbolId(scope=("left.arm",), local_id="drive.v1")),
        logical_resource_port_id(SymbolId(scope=("right.arm",), local_id="drive.v1")),
    )
    assert [binding.port_path for binding in assembly.bindings] == [
        "left.arm/drive.v1.set.frequency.value.path",
        "right.arm/drive.v1.set.frequency.value.path",
    ]
    assert [binding.capability_id for binding in assembly.bindings] == [
        "set.frequency",
        "set.frequency",
    ]
    assert [binding.field_path for binding in assembly.bindings] == [
        "value.path",
        "value.path",
    ]
    assert [product.resource_port_id for product in assembly.product_ports] == [
        logical_resource_port_id(SymbolId(scope=("left.arm",), local_id="drive.v1")),
        logical_resource_port_id(SymbolId(scope=("right.arm",), local_id="drive.v1")),
    ]
    definitions = {
        definition.id: definition for definition in assembly.semantic_graph.value_defs
    }
    routes = [
        definitions[dict(operation.inputs)["route"].value_id].source
        for operation in assembly.semantic_graph.operations
    ]
    assert all(isinstance(route, RouteValueSource) for route in routes)
    assert [
        route.port_id for route in routes if isinstance(route, RouteValueSource)
    ] == [
        logical_resource_port_id(SymbolId(scope=("left.arm",), local_id="drive.v1")),
        logical_resource_port_id(SymbolId(scope=("right.arm",), local_id="drive.v1")),
    ]

    resolved = resolve_experiment(
        root.template("test.resources.root", kind="resources").build().bind(),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    assert [state.capability_id for state in resolved.experiment.state] == [
        "set.frequency",
        "set.frequency",
    ]
    assert [state.field_path for state in resolved.experiment.state] == [
        "value.path",
        "value.path",
    ]


def test_nested_instances_prefix_resource_references_once_per_level() -> None:
    inner = _resource_module().instantiate("inner")
    wrapper = sc.module("test.resources.wrapper").use(inner).build()
    outer = wrapper.instantiate("outer")
    root = sc.module("test.resources.nested-root").use(outer).build()

    assembly = elaborate_module(root)
    verified = verify_assembly_graph(assembly)

    expected_port_id = logical_resource_port_id(
        SymbolId(
            scope=("outer", "inner"),
            local_id="drive.v1",
        )
    )
    assert tuple(verified.resource_ports) == (expected_port_id,)
    assert assembly.bindings[0].port_path == (
        "outer/inner/drive.v1.set.frequency.value.path"
    )
    assert assembly.product_ports[0].resource_port_id == expected_port_id
    operation = assembly.semantic_graph.operations[0]
    route_definition = next(
        definition
        for definition in assembly.semantic_graph.value_defs
        if definition.id == dict(operation.inputs)["route"].value_id
    )
    route = route_definition.source
    assert isinstance(route, RouteValueSource)
    assert route.port_id == expected_port_id


def test_resource_identity_distinguishes_slash_from_nested_scope() -> None:
    child = _resource_module()
    direct = child.instantiate("outer/inner")
    nested_child = child.instantiate("inner")
    wrapper = sc.module("test.resources.wrapper").use(nested_child).build()
    nested = wrapper.instantiate("outer")
    root = sc.module("test.resources.identity-root").use(direct, nested).build()

    assembly = elaborate_module(root)
    verified = verify_assembly_graph(assembly)

    direct_id = logical_resource_port_id(
        SymbolId(scope=("outer/inner",), local_id="drive.v1")
    )
    nested_id = logical_resource_port_id(
        SymbolId(scope=("outer", "inner"), local_id="drive.v1")
    )
    assert direct_id != nested_id
    assert set(verified.resource_ports) == {direct_id, nested_id}
    assert {product.resource_port_id for product in assembly.product_ports} == {
        direct_id,
        nested_id,
    }
    definitions = {
        definition.id: definition for definition in assembly.semantic_graph.value_defs
    }
    assert {
        definition.source.port_id
        for operation in assembly.semantic_graph.operations
        for _name, value in operation.inputs
        if isinstance(
            (definition := definitions[value.value_id]).source,
            RouteValueSource,
        )
    } == {direct_id, nested_id}


def test_record_resource_references_are_checked_before_linking() -> None:
    with pytest.raises(CheckFailed) as error:
        (
            sc.module("test.resources.missing-record-port")
            .record("fixed", resource="missing")
            .product("exported", resource="missing")
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_undeclared",
    ]


def test_record_resource_capabilities_are_checked_before_linking() -> None:
    module = (
        sc.module("test.resources.missing-record-capability")
        .resource("readout", requires=("measure.iq",))
        .record(
            "fixed",
            resource="readout",
            capability="measure.phase",
        )
        .product(
            "exported",
            resource="readout",
            capability="measure.population",
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module))

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_port_capability_missing",
        "module_resource_port_capability_missing",
    ]
    assert [problem.location for problem in error.value.problems] == [
        model_location("records", "fixed", "capability"),
        model_location("products", "exported", "capability"),
    ]


def test_state_resource_references_are_checked_before_linking() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)),
    )
    with pytest.raises(CheckFailed) as error:
        (
            sc.module("test.resources.missing-state-port")
            .inputs(rows)
            .bind_field(
                "missing-binding",
                capability="set.offset",
                field="value",
                value=1.0,
            )
            .state_each(
                rows,
                resource_port="missing-state",
                capability="set.offset",
                field="value",
                value=lambda row: row["value"],
            )
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_undeclared",
        "module_resource_undeclared",
    ]


def test_state_resource_capabilities_are_checked_before_linking() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)),
    )
    module = (
        sc.module("test.resources.missing-state-capability")
        .inputs(rows)
        .resource("drive", requires=("set.frequency",))
        .bind_field(
            "drive",
            capability="set.power",
            field="value",
            value=1.0,
        )
        .state_each(
            rows,
            resource_port="drive",
            capability="set.offset",
            field="value",
            value=lambda row: row["value"],
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module))

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_port_capability_missing",
        "module_resource_port_capability_missing",
    ]


def test_state_each_keeps_dotted_capability_and_field_ids_structured(
    tmp_path: Path,
) -> None:
    rows_type = sc.TableType(
        columns=(
            sc.TableColumn("resource", sc.ScalarType(sc.StringType())),
            sc.TableColumn("value", sc.ScalarType(sc.FloatType())),
        )
    )
    rows = sc.input("rows", rows_type)
    child = (
        sc.module("test.resources.structured-state")
        .inputs(rows)
        .state_each(
            rows,
            resource=lambda row: row["resource"],
            capability="set.offset",
            field="value.path",
            value=lambda row: row["value"],
        )
        .build()
    )
    instance = child.instantiate(
        "state.arm",
        rows=({"resource": "source-0", "value": 1.0},),
    )
    root = sc.module("test.resources.structured-state-root").use(instance).build()

    resolved = resolve_experiment(
        root.template("test.resources.structured-state", kind="resources")
        .build()
        .bind(),
        workspace=tmp_path,
        config_profile=load_config(),
    )

    state = resolved.experiment.state[0]
    assert state.state is not None
    assert state.state[0].capability_id == "set.offset"
    assert state.state[0].field_path == "value.path"
