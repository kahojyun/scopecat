# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, cast

import pytest

import scopecat as sc
from scopecat.execution.local.program import ApplyStateOperation
from scopecat.planning.local_materialization import (
    materialize_local_final_state,
    prepare_local_target,
)
from scopecat.program.bindings import EnsureStateIntent
from scopecat.program.logical import LogicalEnsureState
from scopecat.sdk.instruments import InterfaceRef, PropertyRef
from tests.testkit.authoring import bind_invocation
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


@dataclass(frozen=True)
class _NullTarget:
    def target_assignments(self) -> Mapping[PropertyRef, sc.StateBinding]:
        return {_SOURCE_ENABLED: cast("sc.StateBinding", cast("object", None))}


@dataclass(frozen=True)
class _DeclaredSourceState:
    level: sc.StateBinding
    enabled: sc.StateBinding


@dataclass(frozen=True)
class _TypedSource:
    resource: sc.DefinitionResource

    def finalization_targets(
        self,
        state: _DeclaredSourceState,
        /,
    ) -> tuple[sc.FinalizationTarget, ...]:
        return (
            (
                self.resource,
                _SourceTarget(level=state.level, enabled=state.enabled),
            ),
        )


def test_ensure_binds_one_declarative_target_with_point_resolved_values() -> None:
    @sc.module(id="test.desired-state")
    def desired_state(
        module: sc.ModuleContext,
        level: Annotated[
            sc.Input[sc.Quantity],
            sc.ScalarType(sc.QuantityType(unit="V")),
        ],
    ) -> None:
        source = module.resource("source", requires=(_SOURCE,))
        module.ensure(
            source,
            _SourceTarget(level=level, enabled=True),
        )

    assert [binding.property_id for binding in desired_state.bindings] == [
        "level",
        "enabled",
    ]
    assert isinstance(desired_state.bindings[0].value, sc.ValueRef)
    assert desired_state.bindings[1].value is True
    [effect] = desired_state.effects
    assert isinstance(effect, EnsureStateIntent)
    assert len(effect.assignments) == 2


def test_ensure_rejects_an_empty_target() -> None:
    with pytest.raises(
        ValueError,
        match="ensure requires at least one target assignment",
    ):

        @sc.module(id="test.empty-target")
        def empty_target(module: sc.ModuleContext) -> None:
            source = module.resource("source")
            module.ensure(source, _EmptyTarget())


def test_ensure_rejects_none_at_the_authoring_boundary() -> None:
    with pytest.raises(TypeError, match="state bindings cannot be None"):

        @sc.module(id="test.none-target")
        def none_target(module: sc.ModuleContext) -> None:
            source = module.resource("source", requires=(_SOURCE,))
            module.ensure(source, _NullTarget())


def test_bind_property_rejects_none_at_the_authoring_boundary() -> None:
    with pytest.raises(TypeError, match="state bindings cannot be None"):

        @sc.module(id="test.none-binding")
        def none_binding(module: sc.ModuleContext) -> None:
            source = module.resource("source", requires=(_SOURCE,))
            module.bind_property(
                source,
                _SOURCE_ENABLED,
                value=cast("sc.StateBinding", cast("object", None)),
            )


def test_ensure_remains_one_coherent_effect_through_local_planning() -> None:
    @sc.module(id="test.coherent-target")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SOURCE,))
        context.ensure(source, _SourceTarget(level=1.5, enabled=True))

    @sc.template(id="test.coherent-target", kind="desired-state")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(module())

    bound = bind_invocation(
        template(),
        config_profile=config_with_physical_resources(
            {"source-device": (_SOURCE.interface_id,)}
        ),
    )

    [effect] = bound.program.program.effects
    assert isinstance(effect, LogicalEnsureState)
    assert [assignment.property_id for assignment in effect.assignments] == [
        "level",
        "enabled",
    ]

    plan = materialize_local_execution(bound)
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
    @sc.module(id="test.sequential-targets")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_SOURCE,))
        context.ensure(source, _SourceTarget(level=1.0, enabled=True))
        context.ensure(source, _SourceTarget(level=2.0, enabled=False))

    @sc.template(id="test.sequential-targets", kind="desired-state")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(module())

    bound = bind_invocation(
        template(),
        config_profile=config_with_physical_resources(
            {"source-device": (_SOURCE.interface_id,)}
        ),
    )

    assert all(
        isinstance(effect, LogicalEnsureState)
        for effect in bound.program.program.effects
    )
    plan = materialize_local_execution(bound)
    operations = tuple(
        effect.operation
        for effect in plan.effects
        if isinstance(effect.operation, ApplyStateOperation)
    )
    assert len(operations) == 2
    assert [operation.targets[0].value.root for operation in operations] == [1.0, 2.0]


def test_root_final_state_is_materialized_outside_point_effects() -> None:
    @sc.module(id="test.final_state-module")
    def module(context: sc.ModuleContext) -> None:
        context.resource("source", requires=(_SOURCE,))

    @sc.template(id="test.final_state", kind="desired-state")
    def experiment_definition(
        experiment: sc.ExperimentContext,
        level: float = 0.0,
    ) -> None:
        call = experiment.run(module())
        experiment.finalize(
            call.resources.source,
            _SourceTarget(level=level, enabled=False),
        )

    bound = bind_invocation(
        experiment_definition(),
        config_profile=config_with_physical_resources(
            {"source-device": (_SOURCE.interface_id,)}
        ),
    )

    assert bound.program.program.effects == ()
    final_state = bound.program.program.final_state
    assert isinstance(final_state, LogicalEnsureState)
    assert [assignment.property_id for assignment in final_state.assignments] == [
        "level",
        "enabled",
    ]
    target = prepare_local_target(
        bound,
        product_use_ids=frozenset(),
        instrument_order=("source-device",),
    )
    [operation] = materialize_local_final_state(bound, target=target)
    assert operation.instrument_id == "source-device"
    assert [target.property_id for target in operation.targets] == [
        "level",
        "enabled",
    ]
    assert operation.targets[0].value.root == 0.0


def test_root_final_state_accepts_a_typed_finalization_adapter() -> None:
    @sc.template(id="test.typed-final-state", kind="desired-state")
    def experiment_definition(experiment: sc.ExperimentContext) -> None:
        source = experiment.resource("source", requires=(_SOURCE,))
        typed_source: sc.Finalizable[_DeclaredSourceState] = _TypedSource(source)
        experiment.finalize(
            typed_source,
            _DeclaredSourceState(level=0.0, enabled=False),
        )

    final_state = experiment_definition.definition.final_state
    assert final_state is not None
    assert [assignment.property_id for assignment in final_state.assignments] == [
        "level",
        "enabled",
    ]


def test_root_final_state_rejects_scan_coordinates() -> None:
    @sc.module(id="test.final_state-coordinate")
    def module(context: sc.ModuleContext) -> None:
        context.resource("source", requires=(_SOURCE,))

    call = module()
    level = sc.coordinate("level", sc.ScalarType(sc.FloatType()))

    with pytest.raises(
        ValueError,
        match="final_state cannot depend on scan coordinates",
    ):

        @sc.template(id="test.final_state-coordinate", kind="desired-state")
        def experiment_definition(experiment: sc.ExperimentContext) -> None:
            experiment.run(call)
            experiment.finalize(
                call.resources.source,
                _SourceTarget(level=level, enabled=False),
            )
