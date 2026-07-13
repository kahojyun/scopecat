from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.authoring._graph_validation import verify_assembly_graph
from scopecat.authoring._module_composition import assemble_module_internal
from scopecat.authoring._resolution import resolve_experiment
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

    assembly = assemble_module_internal(root)
    verified = verify_assembly_graph(assembly)

    assert tuple(verified.resource_ports) == (
        "left.arm/drive.v1",
        "right.arm/drive.v1",
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
    assert [product.resource for product in assembly.product_ports] == [
        "left.arm/drive.v1",
        "right.arm/drive.v1",
    ]
    routes = [dict(node.inputs)["route"] for node in assembly.compute_nodes]
    assert all(isinstance(route, sc.RouteRef) for route in routes)
    assert [route.port_id for route in routes if isinstance(route, sc.RouteRef)] == [
        "left.arm/drive.v1",
        "right.arm/drive.v1",
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

    assembly = assemble_module_internal(root)
    verified = verify_assembly_graph(assembly)

    assert tuple(verified.resource_ports) == ("outer/inner/drive.v1",)
    assert assembly.bindings[0].port_path == (
        "outer/inner/drive.v1.set.frequency.value.path"
    )
    assert assembly.product_ports[0].resource == "outer/inner/drive.v1"
    route = dict(assembly.compute_nodes[0].inputs)["route"]
    assert isinstance(route, sc.RouteRef)
    assert route.port_id == "outer/inner/drive.v1"


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
