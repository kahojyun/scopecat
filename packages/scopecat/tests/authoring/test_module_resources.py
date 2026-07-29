from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._binding_intents import BindingIntent
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    core_state,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import link_invocation, load_config, template_fixture
from tests.testkit.materialized_effects import config_with_physical_resources

_SET_FREQUENCY = InterfaceRef("test.set_frequency/v1")
_SET_FREQUENCY_VALUE_PATH = _SET_FREQUENCY.property("value.path")
_SET_FREQUENCY_SAMPLE_SIGNAL = _SET_FREQUENCY.acquisition("sample").result("signal")
_MEASURE_IQ = InterfaceRef("test.measure_iq/v1")
_MEASURE_IQ_SAMPLE_EXPORTED = _MEASURE_IQ.acquisition("sample").result("exported")
_MEASURE_PHASE_SAMPLE_FIXED = (
    InterfaceRef("test.measure_phase/v1").acquisition("sample").result("fixed")
)
_MEASURE_POPULATION_SAMPLE_EXPORTED = (
    InterfaceRef("test.measure_population/v1").acquisition("sample").result("exported")
)
_SET_OFFSET = InterfaceRef("test.set_offset/v1")
_SET_OFFSET_VALUE = _SET_OFFSET.property("value")
_SET_OFFSET_VALUE_PATH = _SET_OFFSET.property("value.path")
_SET_POWER_VALUE = InterfaceRef("test.set_power/v1").property("value")


def _resource_module() -> sc.ExperimentModule[...]:
    frequency = sc.Quantity(value=5.0, unit="GHz")
    return (
        sc.module_body(id="test.resources.child")
        .resource("drive.v1", requires=(_SET_FREQUENCY,))
        .bind_property(
            "drive.v1",
            _SET_FREQUENCY_VALUE_PATH,
            value=frequency,
        )
        .product("signal")
        .acquire(
            "read-signal",
            resource="drive.v1",
            results={_SET_FREQUENCY_SAMPLE_SIGNAL: "signal"},
        )
        .build()
    )


def test_graph_proof_indexes_verified_product_declarations() -> None:
    assembly = elaborate_module(_resource_module().ir)

    verified = verify_assembly_graph(assembly)

    assert tuple(verified.product_declarations) == tuple(
        product.product_id for product in assembly.product_declarations
    )


def test_explicit_instances_own_independent_resource_ports() -> None:
    child = _resource_module()
    left = child.instantiate("left.arm")
    right = child.instantiate("right.arm")
    root = sc.module_body(id="test.resources.root").use(left, right).build()

    assembly = elaborate_module(root.ir)
    verify_assembly_graph(assembly)

    assert tuple(port.symbol_id for port in assembly.resource_ports) == (
        logical_resource_port_id(SymbolId(scope=("left.arm",), local_id="drive.v1")),
        logical_resource_port_id(SymbolId(scope=("right.arm",), local_id="drive.v1")),
    )
    assert [binding.interface_id for binding in assembly.bindings] == [
        "test.set_frequency/v1",
        "test.set_frequency/v1",
    ]
    assert [binding.property_id for binding in assembly.bindings] == [
        "value.path",
        "value.path",
    ]
    assert [acquire.resource_port_id for acquire in assembly.acquisitions] == [
        logical_resource_port_id(SymbolId(scope=("left.arm",), local_id="drive.v1")),
        logical_resource_port_id(SymbolId(scope=("right.arm",), local_id="drive.v1")),
    ]
    call = root()

    @sc.template(id="test.resources.root", kind="resources")
    def template_definition() -> sc.ExperimentBody:
        return sc.experiment(call)

    resolved = link_invocation(
        template_definition(),
        config_profile=load_config(),
    )
    assert [
        state.interface_id
        for state in core_state(resolved.program)
        if isinstance(state, SetStateSpec)
    ] == [
        "test.set_frequency/v1",
        "test.set_frequency/v1",
    ]
    assert [
        state.property_id
        for state in core_state(resolved.program)
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
        sc.module_body(id="test.resources.bound-root")
        .resource("shared", requires=(_SET_FREQUENCY,))
        .use(child)
        .build()
    )

    assembly = elaborate_module(root.ir)

    assert tuple(port.qualified_id for port in assembly.resource_ports) == ("shared",)
    assert tuple(binding.port_id.qualified_name for binding in assembly.bindings) == (
        "shared",
    )
    assert tuple(
        acquire.resource_port_id.qualified_name for acquire in assembly.acquisitions
    ) == ("shared",)


def test_nested_instances_prefix_resource_references_once_per_level() -> None:
    inner = _resource_module().instantiate("inner")
    wrapper = sc.module_body(id="test.resources.wrapper").use(inner).build()
    outer = wrapper.instantiate("outer")
    root = sc.module_body(id="test.resources.nested-root").use(outer).build()

    assembly = elaborate_module(root.ir)
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
    assert assembly.acquisitions[0].resource_port_id == expected_port_id


def test_hierarchical_effects_keep_source_order_and_duplicate_occurrences() -> None:
    value = sc.Quantity(value=5.0, unit="GHz")
    program = sc.domain_program(
        "noop",
        dialect_id="test",
        dialect_version="1",
        body=object(),
    )
    child_builder = (
        sc.module_body(id="test.effects.child")
        .resource("drive.v1", requires=(_SET_FREQUENCY,))
        .bind_property(
            "drive.v1",
            _SET_FREQUENCY_VALUE_PATH,
            value=value,
        )
        .domain(sc.domain_execution(program, id="call"))
        .product("signal")
    )
    child = (
        child_builder.acquire(
            "read-signal",
            resource="drive.v1",
            results={_SET_FREQUENCY_SAMPLE_SIGNAL: "signal"},
        )
        .build()
        .instantiate(
            "child",
            resource_bindings={"drive.v1": "drive.v1"},
        )
    )
    root_builder = (
        sc.module_body(id="test.effects.root")
        .resource("drive.v1", requires=(_SET_FREQUENCY,))
        .bind_property(
            "drive.v1",
            _SET_FREQUENCY_VALUE_PATH,
            value=value,
        )
        .use(child)
        .bind_property(
            "drive.v1",
            _SET_FREQUENCY_VALUE_PATH,
            value=value,
        )
        .domain(sc.domain_execution(program, id="root-call"))
        .product("root-signal")
    )
    module = root_builder.acquire(
        "root-read",
        resource="drive.v1",
        results={_SET_FREQUENCY_SAMPLE_SIGNAL: "root-signal"},
    ).build()
    assembly = elaborate_module(module.ir)

    assert [
        ("binding", effect.port_id.qualified_name)
        if isinstance(effect, BindingIntent)
        else ("acquire", effect.id.qualified_name)
        if isinstance(effect, AcquireEffect)
        else ("domain", effect.id)
        for effect in assembly.effects
    ] == [
        ("binding", "drive.v1"),
        ("binding", "drive.v1"),
        ("domain", "child/call"),
        ("acquire", "child/read-signal"),
        ("binding", "drive.v1"),
        ("domain", "root-call"),
        ("acquire", "root-read"),
    ]

    template = template_fixture(
        module,
        id="test.effects.root",
        kind="effects",
    )
    linked = link_invocation(template(), config_profile=load_config())
    assert [
        "binding"
        if isinstance(effect, SetStateSpec)
        else f"acquire:{effect.id.qualified_name}"
        if isinstance(effect, AcquireEffect)
        else f"domain:{effect.id}"
        for effect in linked.program.effects
    ] == [
        "binding",
        "binding",
        "domain:child/call",
        "acquire:child/read-signal",
        "binding",
        "domain:root-call",
        "acquire:root-read",
    ]
    assert (
        sum(isinstance(effect, SetStateSpec) for effect in linked.program.effects) == 3
    )
    assert (
        sum(
            isinstance(effect, TypedDomainExecution)
            for effect in linked.program.effects
        )
        == 2
    )


def test_resource_identity_distinguishes_slash_from_nested_scope() -> None:
    child = _resource_module()
    direct = child.instantiate("outer/inner")
    nested_child = child.instantiate("inner")
    wrapper = sc.module_body(id="test.resources.wrapper").use(nested_child).build()
    nested = wrapper.instantiate("outer")
    root = sc.module_body(id="test.resources.identity-root").use(direct, nested).build()

    assembly = elaborate_module(root.ir)
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
    assert {acquire.resource_port_id for acquire in assembly.acquisitions} == {
        direct_id,
        nested_id,
    }


def test_acquire_resource_references_are_checked_before_linking() -> None:
    with pytest.raises(CheckFailed) as error:
        (
            sc.module_body(id="test.resources.missing-record-port")
            .product("exported")
            .acquire(
                "read-exported",
                resource="missing",
                results={_MEASURE_IQ_SAMPLE_EXPORTED: "exported"},
            )
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_undeclared",
    ]


def test_acquire_resource_interfaces_are_checked_before_linking() -> None:
    module = (
        sc.module_body(id="test.resources.missing-record-interface")
        .resource("readout", requires=(_MEASURE_IQ,))
        .product("fixed", "exported")
        .acquire(
            "read-fixed",
            resource="readout",
            results={_MEASURE_PHASE_SAMPLE_FIXED: "fixed"},
        )
        .acquire(
            "read-exported",
            resource="readout",
            results={_MEASURE_POPULATION_SAMPLE_EXPORTED: "exported"},
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module.ir))

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_port_interface_missing",
        "module_resource_port_interface_missing",
    ]
    assert [problem.location for problem in error.value.problems] == [
        model_location("acquisitions", 0, "resource_port"),
        model_location("acquisitions", 1, "resource_port"),
    ]


def test_state_resource_references_are_checked_before_linking() -> None:
    with pytest.raises(CheckFailed) as error:
        (
            sc.module_body(id="test.resources.missing-state-port")
            .bind_property(
                "missing-binding",
                _SET_OFFSET_VALUE,
                value=1.0,
            )
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_undeclared",
    ]


def test_state_resource_interfaces_are_checked_before_linking() -> None:
    module = (
        sc.module_body(id="test.resources.missing-state-interface")
        .resource("drive", requires=(_SET_FREQUENCY,))
        .bind_property(
            "drive",
            _SET_POWER_VALUE,
            value=1.0,
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module.ir))

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_port_interface_missing",
    ]


def test_state_binding_keeps_interface_and_property_ids_structured() -> None:
    child = (
        sc.module_body(id="test.resources.structured-state")
        .resource("source", requires=(_SET_OFFSET,))
        .bind_property(
            "source",
            _SET_OFFSET_VALUE_PATH,
            value=1.0,
        )
        .build()
    )
    instance = child.instantiate("state.arm")
    root = (
        sc.module_body(id="test.resources.structured-state-root").use(instance).build()
    )
    call = root()

    @sc.template(id="test.resources.structured-state", kind="resources")
    def template_definition() -> sc.ExperimentBody:
        return sc.experiment(call)

    resolved = link_invocation(
        template_definition(),
        config_profile=config_with_physical_resources(
            {"source-0": ("test.set_offset/v1",)}
        ),
    )

    state = core_state(resolved.program)[0]
    assert isinstance(state, SetStateSpec)
    assert state.interface_id == "test.set_offset/v1"
    assert state.property_id == "value.path"
