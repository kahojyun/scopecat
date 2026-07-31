from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import compose_module
from scopecat.compiler.frontend.logical_verification import verify_logical_program
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.typed.invocation import InvokeEffect
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    core_state,
)
from scopecat.compiler.typed.state import EnsureStateSpec, SetStateSpec
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
)
from scopecat.program.domain import domain_program
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import bind_invocation, load_config
from tests.testkit.domain import domain_call
from tests.testkit.materialized_effects import config_with_physical_resources

_SET_FREQUENCY = InterfaceRef("test.set_frequency/v1")
_SET_FREQUENCY_VALUE_PATH = _SET_FREQUENCY.property("value.path")
_SET_FREQUENCY_SAMPLE_SIGNAL = _SET_FREQUENCY.acquisition("sample").result("signal")


def test_definition_resources_are_owned_by_their_context() -> None:
    left = sc.ModuleContext()
    right = sc.ModuleContext()
    foreign = left.resource("drive", requires=(_SET_FREQUENCY,))
    right.resource("drive", requires=(_SET_FREQUENCY,))

    with pytest.raises(ValueError, match="must belong to this module context"):
        right.bind_property(
            foreign,
            _SET_FREQUENCY_VALUE_PATH,
            value=sc.Quantity(value=5.0, unit="GHz"),
        )


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

    @sc.module(id="test.resources.child")
    def module(context: sc.ModuleContext) -> None:
        drive = context.resource("drive.v1", requires=(_SET_FREQUENCY,))
        context.bind_property(
            drive,
            _SET_FREQUENCY_VALUE_PATH,
            value=frequency,
        )
        signal = context.product("signal")
        context.acquire(
            "read-signal",
            resource=drive,
            results={_SET_FREQUENCY_SAMPLE_SIGNAL: signal},
        )

    return module


def test_graph_proof_indexes_verified_product_declarations() -> None:
    assembly = compose_module(_resource_module().ir)

    verified = verify_logical_program(assembly)

    assert tuple(verified.product_declarations) == tuple(
        product.product_id for product in assembly.product_declarations
    )


def test_explicit_instances_own_independent_resource_ports() -> None:
    child = _resource_module()
    left = child.instantiate("left.arm")
    right = child.instantiate("right.arm")

    @sc.module(id="test.resources.root")
    def root(context: sc.ModuleContext) -> None:
        context.call(left)
        context.call(right)

    assembly = compose_module(root.ir)
    verify_logical_program(assembly)

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
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)

    resolved = bind_invocation(
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

    @sc.module(id="test.resources.bound-root")
    def root(context: sc.ModuleContext) -> None:
        context.resource("shared", requires=(_SET_FREQUENCY,))
        context.call(child)

    assembly = compose_module(root.ir)

    assert tuple(port.qualified_id for port in assembly.resource_ports) == ("shared",)
    assert tuple(binding.port_id.qualified_name for binding in assembly.bindings) == (
        "shared",
    )
    assert tuple(
        acquire.resource_port_id.qualified_name for acquire in assembly.acquisitions
    ) == ("shared",)


def test_nested_instances_prefix_resource_references_once_per_level() -> None:
    inner = _resource_module().instantiate("inner")

    @sc.module(id="test.resources.wrapper")
    def wrapper(context: sc.ModuleContext) -> None:
        context.call(inner)

    outer = wrapper.instantiate("outer")

    @sc.module(id="test.resources.nested-root")
    def root(context: sc.ModuleContext) -> None:
        context.call(outer)

    assembly = compose_module(root.ir)
    verify_logical_program(assembly)

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
    program = domain_program(
        "noop",
        dialect_id="test",
        dialect_version="1",
        body=object(),
    )

    @sc.module(id="test.effects.child")
    def child_module(context: sc.ModuleContext) -> None:
        drive = context.resource("drive.v1", requires=(_SET_FREQUENCY,))
        context.bind_property(
            drive,
            _SET_FREQUENCY_VALUE_PATH,
            value=value,
        )
        context.call(domain_call(program, id="call"))
        signal = context.product("signal")
        context.acquire(
            "read-signal",
            resource=drive,
            results={_SET_FREQUENCY_SAMPLE_SIGNAL: signal},
        )

    child = child_module.instantiate(
        "child",
        resource_bindings={"drive.v1": "drive.v1"},
    )

    @sc.module(id="test.effects.root")
    def module(context: sc.ModuleContext) -> None:
        drive = context.resource("drive.v1", requires=(_SET_FREQUENCY,))
        context.bind_property(
            drive,
            _SET_FREQUENCY_VALUE_PATH,
            value=value,
        )
        context.call(child)
        context.bind_property(
            drive,
            _SET_FREQUENCY_VALUE_PATH,
            value=value,
        )
        context.call(domain_call(program, id="root-call"))
        root_signal = context.product("root-signal")
        context.acquire(
            "root-read",
            resource=drive,
            results={_SET_FREQUENCY_SAMPLE_SIGNAL: root_signal},
        )

    assembly = compose_module(module.ir)

    assert [
        ("binding", effect.port_id.qualified_name)
        if isinstance(effect, BindingIntent)
        else ("acquire", effect.id.qualified_name)
        if isinstance(effect, AcquireEffect)
        else ("ensure", str(len(effect.assignments)))
        if isinstance(effect, EnsureStateIntent)
        else ("invoke", effect.id)
        if isinstance(effect, InvocationIntent)
        else ("domain", effect.id)
        for effect in assembly.effects
    ] == [
        ("binding", "drive.v1"),
        ("binding", "drive.v1"),
        ("domain", "child/call/noop"),
        ("acquire", "child/read-signal"),
        ("binding", "drive.v1"),
        ("domain", "root-call/noop"),
        ("acquire", "root-read"),
    ]

    @sc.template(id="test.effects.root", kind="effects")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(module.instantiate("root"))

    bound = bind_invocation(template(), config_profile=load_config())
    assert [
        "binding"
        if isinstance(effect, SetStateSpec)
        else f"acquire:{effect.id.qualified_name}"
        if isinstance(effect, AcquireEffect)
        else f"ensure:{len(effect.assignments)}"
        if isinstance(effect, EnsureStateSpec)
        else f"invoke:{effect.id.qualified_name}"
        if isinstance(effect, InvokeEffect)
        else f"domain:{effect.id}"
        for effect in bound.program.effects
    ] == [
        "binding",
        "binding",
        "domain:root/child/call/noop",
        "acquire:root/child/read-signal",
        "binding",
        "domain:root/root-call/noop",
        "acquire:root/root-read",
    ]
    assert (
        sum(isinstance(effect, SetStateSpec) for effect in bound.program.effects) == 3
    )
    assert (
        sum(
            isinstance(effect, TypedDomainExecution) for effect in bound.program.effects
        )
        == 2
    )


def test_resource_identity_distinguishes_slash_from_nested_scope() -> None:
    child = _resource_module()
    direct = child.instantiate("outer/inner")
    nested_child = child.instantiate("inner")

    @sc.module(id="test.resources.wrapper")
    def wrapper(context: sc.ModuleContext) -> None:
        context.call(nested_child)

    nested = wrapper.instantiate("outer")

    @sc.module(id="test.resources.identity-root")
    def root(context: sc.ModuleContext) -> None:
        context.call(direct)
        context.call(nested)

    assembly = compose_module(root.ir)
    verify_logical_program(assembly)

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


def test_acquire_resource_interfaces_are_checked_before_linking() -> None:
    @sc.module(id="test.resources.missing-record-interface")
    def module(context: sc.ModuleContext) -> None:
        readout = context.resource("readout", requires=(_MEASURE_IQ,))
        fixed = context.product("fixed")
        exported = context.product("exported")
        context.acquire(
            "read-fixed",
            resource=readout,
            results={_MEASURE_PHASE_SAMPLE_FIXED: fixed},
        )
        context.acquire(
            "read-exported",
            resource=readout,
            results={_MEASURE_POPULATION_SAMPLE_EXPORTED: exported},
        )

    with pytest.raises(CheckFailed) as error:
        verify_logical_program(compose_module(module.ir))

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_port_interface_missing",
        "module_resource_port_interface_missing",
    ]
    assert [problem.location for problem in error.value.problems] == [
        model_location("acquisitions", 0, "resource_port"),
        model_location("acquisitions", 1, "resource_port"),
    ]


def test_state_resource_interfaces_are_checked_before_linking() -> None:
    @sc.module(id="test.resources.missing-state-interface")
    def module(context: sc.ModuleContext) -> None:
        drive = context.resource("drive", requires=(_SET_FREQUENCY,))
        context.bind_property(
            drive,
            _SET_POWER_VALUE,
            value=1.0,
        )

    with pytest.raises(CheckFailed) as error:
        verify_logical_program(compose_module(module.ir))

    assert [problem.code for problem in error.value.problems] == [
        "module_resource_port_interface_missing",
    ]


def test_state_binding_keeps_interface_and_property_ids_structured() -> None:
    @sc.module(id="test.resources.structured-state")
    def child(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SET_OFFSET,))
        context.bind_property(
            source,
            _SET_OFFSET_VALUE_PATH,
            value=1.0,
        )

    instance = child.instantiate("state.arm")

    @sc.module(id="test.resources.structured-state-root")
    def root(context: sc.ModuleContext) -> None:
        context.call(instance)

    call = root()

    @sc.template(id="test.resources.structured-state", kind="resources")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)

    resolved = bind_invocation(
        template_definition(),
        config_profile=config_with_physical_resources(
            {"source-0": ("test.set_offset/v1",)}
        ),
    )

    state = core_state(resolved.program)[0]
    assert isinstance(state, SetStateSpec)
    assert state.interface_id == "test.set_offset/v1"
    assert state.property_id == "value.path"
