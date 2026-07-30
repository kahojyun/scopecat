from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

import scopecat as sc
from scopecat.sdk.instruments import InterfaceRef, PropertyRef

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
        sc.module_body(id="test.desired-state")
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


def test_ensure_rejects_an_empty_target() -> None:
    with pytest.raises(
        ValueError,
        match="ensure requires at least one target assignment",
    ):
        sc.module_body(id="test.empty-target").ensure("source", _EmptyTarget())
