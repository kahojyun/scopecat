from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.typed.program import core_state
from scopecat.compiler.typed.state import ForEachStateSpec, SetStateSpec
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.planning.authoring import resolve_experiment
from tests.testkit.authoring import load_config
from tests.testkit.materialized_effects import config_with_physical_resources


def _resource_module() -> sc.ExperimentModule:
    frequency = sc.Quantity(value=5.0, unit="GHz")
    return (
        sc.module("test.resources.child")
        .resource("drive.v1", requires=("set.frequency",))
        .bind_field(
            "drive.v1",
            capability="set.frequency",
            field="value.path",
            value=frequency,
        )
        .product("signal")
        .acquire(
            "read-signal",
            "signal",
            resource="drive.v1",
            capability="set.frequency",
        )
        .build()
    )


def test_graph_proof_indexes_verified_product_declarations() -> None:
    assembly = elaborate_module(_resource_module())

    verified = verify_assembly_graph(assembly)

    assert tuple(verified.product_declarations) == tuple(
        product.product_id for product in assembly.product_declarations
    )


def test_explicit_instances_own_independent_resource_ports() -> None:
    child = _resource_module()
    left = child.instantiate("left.arm")
    right = child.instantiate("right.arm")
    root = sc.module("test.resources.root").use(left, right).build()

    assembly = elaborate_module(root)
    verify_assembly_graph(assembly)

    assert tuple(port.symbol_id for port in assembly.resource_ports) == (
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
    assert [
        acquire.resource_port_id for acquire in assembly.semantic_graph.acquisitions
    ] == [
        logical_resource_port_id(SymbolId(scope=("left.arm",), local_id="drive.v1")),
        logical_resource_port_id(SymbolId(scope=("right.arm",), local_id="drive.v1")),
    ]
    resolved = resolve_experiment(
        root.template("test.resources.root", kind="resources").build().bind(),
        config_profile=load_config(),
    )
    assert [
        state.capability_id
        for state in core_state(resolved.experiment)
        if isinstance(state, SetStateSpec)
    ] == [
        "set.frequency",
        "set.frequency",
    ]
    assert [
        state.field_path
        for state in core_state(resolved.experiment)
        if isinstance(state, SetStateSpec)
    ] == [
        "value.path",
        "value.path",
    ]


def test_child_resource_port_can_bind_to_parent_resource_port() -> None:
    child = _resource_module().instantiate(
        "nested",
        resource_bindings={"drive.v1": "shared"},
    )
    root = (
        sc.module("test.resources.bound-root")
        .resource("shared", requires=("set.frequency",))
        .use(child)
        .build()
    )

    assembly = elaborate_module(root)

    assert tuple(port.qualified_id for port in assembly.resource_ports) == ("shared",)
    assert tuple(binding.port_id.qualified_name for binding in assembly.bindings) == (
        "shared",
    )
    assert tuple(
        acquire.resource_port_id.qualified_name
        for acquire in assembly.semantic_graph.acquisitions
    ) == ("shared",)


def test_nested_instances_prefix_resource_references_once_per_level() -> None:
    inner = _resource_module().instantiate("inner")
    wrapper = sc.module("test.resources.wrapper").use(inner).build()
    outer = wrapper.instantiate("outer")
    root = sc.module("test.resources.nested-root").use(outer).build()

    assembly = elaborate_module(root)
    verify_assembly_graph(assembly)

    expected_port_id = logical_resource_port_id(
        SymbolId(
            scope=("outer", "inner"),
            local_id="drive.v1",
        )
    )
    assert tuple(port.symbol_id for port in assembly.resource_ports) == (
        expected_port_id,
    )
    assert assembly.bindings[0].port_path == (
        "outer/inner/drive.v1.set.frequency.value.path"
    )
    assert assembly.semantic_graph.acquisitions[0].resource_port_id == expected_port_id


def test_resource_identity_distinguishes_slash_from_nested_scope() -> None:
    child = _resource_module()
    direct = child.instantiate("outer/inner")
    nested_child = child.instantiate("inner")
    wrapper = sc.module("test.resources.wrapper").use(nested_child).build()
    nested = wrapper.instantiate("outer")
    root = sc.module("test.resources.identity-root").use(direct, nested).build()

    assembly = elaborate_module(root)
    verify_assembly_graph(assembly)

    direct_id = logical_resource_port_id(
        SymbolId(scope=("outer/inner",), local_id="drive.v1")
    )
    nested_id = logical_resource_port_id(
        SymbolId(scope=("outer", "inner"), local_id="drive.v1")
    )
    assert direct_id != nested_id
    assert {port.symbol_id for port in assembly.resource_ports} == {
        direct_id,
        nested_id,
    }
    assert {
        acquire.resource_port_id for acquire in assembly.semantic_graph.acquisitions
    } == {
        direct_id,
        nested_id,
    }


def test_acquire_resource_references_are_checked_before_linking() -> None:
    with pytest.raises(CheckFailed) as error:
        (
            sc.module("test.resources.missing-record-port")
            .product("exported")
            .acquire(
                "read-exported",
                "exported",
                resource="missing",
                capability="measure.iq",
            )
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_undeclared",
    ]


def test_acquire_resource_capabilities_are_checked_before_linking() -> None:
    module = (
        sc.module("test.resources.missing-record-capability")
        .resource("readout", requires=("measure.iq",))
        .product("fixed", "exported")
        .acquire(
            "read-fixed",
            "fixed",
            resource="readout",
            capability="measure.phase",
        )
        .acquire(
            "read-exported",
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
        model_location("acquisitions", 0, "resource_port"),
        model_location("acquisitions", 1, "resource_port"),
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


def test_state_each_keeps_dotted_capability_and_field_ids_structured() -> None:
    rows_type = sc.TableType(
        columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)
    )
    rows = sc.input("rows", rows_type)
    child = (
        sc.module("test.resources.structured-state")
        .inputs(rows)
        .resource("source", requires=("set.offset",))
        .state_each(
            rows,
            resource_port="source",
            capability="set.offset",
            field="value.path",
            value=lambda row: row["value"],
        )
        .build()
    )
    instance = child.instantiate(
        "state.arm",
        rows=({"value": 1.0},),
    )
    root = sc.module("test.resources.structured-state-root").use(instance).build()

    resolved = resolve_experiment(
        root.template("test.resources.structured-state", kind="resources")
        .build()
        .bind(),
        config_profile=config_with_physical_resources({"source-0": ("set.offset",)}),
    )

    state = core_state(resolved.experiment)[0]
    assert isinstance(state, ForEachStateSpec)
    child = state.state[0]
    assert isinstance(child, SetStateSpec)
    assert child.capability_id == "set.offset"
    assert child.field_path == "value.path"
