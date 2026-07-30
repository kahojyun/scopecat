from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

import scopecat as sc
from scopecat.authoring._module_ir import ModuleEnsureEffect
from scopecat.compiler.typed.state import EnsureStateSpec
from scopecat.execution.local.program import ApplyStateOperation
from scopecat.planning.local_materialization import (
    materialize_local_postcondition,
    prepare_local_target,
)
from scopecat.sdk.instruments import InterfaceRef, PropertyRef
from tests.testkit.authoring import link_invocation, template_fixture
from tests.testkit.local_materialization import materialize_local_execution
from tests.testkit.materialized_effects import config_with_physical_resources

_SOURCE = InterfaceRef("test.desired_source/v1")
_SOURCE_LEVEL = _SOURCE.property("level")
_SOURCE_ENABLED = _SOURCE.property("enabled")


@dataclass(frozen=True)
class _SourceTarget:
    level: sc.StateBinding
    enabled: sc.StateBinding

    def target_assignments(self) -> Mapping[PropertyRef, sc.StateBinding]:
        return {
            _SOURCE_LEVEL: self.level,
            _SOURCE_ENABLED: self.enabled,
        }


@dataclass(frozen=True)
class _EmptyTarget:
    def target_assignments(self) -> Mapping[PropertyRef, sc.StateBinding]:
        return {}


def test_ensure_binds_one_declarative_target_with_point_resolved_values() -> None:
    level = sc.coordinate(
        "level",
        sc.ScalarType(sc.QuantityType(unit="V")),
    )

    builder = (
        sc.procedure(id="test.desired-state")
        .resource("source", requires=(_SOURCE,))
        .ensure(
            "source",
            _SourceTarget(level=level, enabled=True),
        )
    )

    assert [binding.property_id for binding in builder.bindings] == [
        "level",
        "enabled",
    ]
    assert builder.bindings[0].value is level
    assert builder.bindings[1].value is True
    [effect] = builder.procedure
    assert isinstance(effect, ModuleEnsureEffect)
    assert len(effect.intent.assignments) == 2


def test_ensure_rejects_an_empty_target() -> None:
    with pytest.raises(
        ValueError,
        match="ensure requires at least one target assignment",
    ):
        sc.procedure(id="test.empty-target").ensure("source", _EmptyTarget())


def test_ensure_remains_one_coherent_effect_through_local_planning() -> None:
    module = (
        sc.procedure(id="test.coherent-target")
        .resource("source", requires=(_SOURCE,))
        .ensure("source", _SourceTarget(level=1.5, enabled=True))
        .build()
    )
    template = template_fixture(
        module,
        id="test.coherent-target",
        kind="desired-state",
    )
    linked = link_invocation(
        template(),
        config_profile=config_with_physical_resources(
            {"source-device": (_SOURCE.interface_id,)}
        ),
    )

    [effect] = linked.program.effects
    assert isinstance(effect, EnsureStateSpec)
    assert [assignment.property_id for assignment in effect.assignments] == [
        "level",
        "enabled",
    ]

    plan = materialize_local_execution(linked)
    operations = tuple(
        effect.operation
        for effect in plan.effects
        if isinstance(effect.operation, ApplyStateOperation)
    )
    assert len(operations) == 1
    assert [target.property_id for target in operations[0].targets] == [
        "level",
        "enabled",
    ]


def test_adjacent_ensure_calls_remain_separate_state_effects() -> None:
    module = (
        sc.procedure(id="test.sequential-targets")
        .resource("source", requires=(_SOURCE,))
        .ensure("source", _SourceTarget(level=1.0, enabled=True))
        .ensure("source", _SourceTarget(level=2.0, enabled=False))
        .build()
    )
    template = template_fixture(
        module,
        id="test.sequential-targets",
        kind="desired-state",
    )
    linked = link_invocation(
        template(),
        config_profile=config_with_physical_resources(
            {"source-device": (_SOURCE.interface_id,)}
        ),
    )

    assert all(isinstance(effect, EnsureStateSpec) for effect in linked.program.effects)
    plan = materialize_local_execution(linked)
    operations = tuple(
        effect.operation
        for effect in plan.effects
        if isinstance(effect.operation, ApplyStateOperation)
    )
    assert len(operations) == 2
    assert [operation.targets[0].value.root for operation in operations] == [1.0, 2.0]


def test_root_postcondition_is_materialized_outside_point_effects() -> None:
    module = (
        sc.procedure(id="test.postcondition-module")
        .resource("source", requires=(_SOURCE,))
        .build()
    )

    @sc.template(id="test.postcondition", kind="desired-state")
    def experiment_definition(level: float = 0.0) -> sc.ExperimentBody:
        call = module()
        return sc.experiment(call).postcondition(
            call.resources.source,
            _SourceTarget(level=level, enabled=False),
        )

    linked = link_invocation(
        experiment_definition(),
        config_profile=config_with_physical_resources(
            {"source-device": (_SOURCE.interface_id,)}
        ),
    )

    assert linked.program.effects == ()
    postcondition = linked.program.postcondition
    assert isinstance(postcondition, EnsureStateSpec)
    assert [assignment.property_id for assignment in postcondition.assignments] == [
        "level",
        "enabled",
    ]
    target = prepare_local_target(
        linked,
        product_use_ids=frozenset(),
        instrument_order=("source-device",),
    )
    [operation] = materialize_local_postcondition(linked, target=target)
    assert operation.instrument_id == "source-device"
    assert [target.property_id for target in operation.targets] == [
        "level",
        "enabled",
    ]
    assert operation.targets[0].value.root == 0.0


def test_root_postcondition_rejects_scan_coordinates() -> None:
    module = (
        sc.procedure(id="test.postcondition-coordinate")
        .resource("source", requires=(_SOURCE,))
        .build()
    )
    call = module()
    level = sc.coordinate("level", sc.ScalarType(sc.FloatType()))

    with pytest.raises(
        ValueError,
        match="postcondition cannot depend on scan coordinates",
    ):
        sc.experiment(call).postcondition(
            call.resources.source,
            _SourceTarget(level=level, enabled=False),
        )
