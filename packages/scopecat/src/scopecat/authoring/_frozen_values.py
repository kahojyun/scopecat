"""Immutable snapshots for values captured by public authoring handles."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Never, cast

import scopecat.kernel.frozen as _frozen
from scopecat.authoring._value_refs import ValueRef
from scopecat.kernel.payloads import PayloadValue
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


def empty_frozen_mapping() -> Mapping[str, Never]:
    """Return an empty immutable mapping usable by covariant public fields."""

    return _frozen.FrozenMapping[str, Never]()


def freeze_runtime_input(value: object) -> object:
    """Snapshot one already-validated closed runtime input."""

    return _freeze_value(value, allow_value_ref=False, allow_payload=False)


def freeze_runtime_inputs(
    values: Mapping[str, object],
) -> _frozen.FrozenMapping[str, object]:
    """Snapshot a named set of already-validated closed runtime inputs."""

    return _frozen.FrozenMapping(
        (name, freeze_runtime_input(value)) for name, value in values.items()
    )


def freeze_module_inputs(
    values: Mapping[str, object],
) -> _frozen.FrozenMapping[str, object]:
    """Snapshot already-validated module inputs, preserving typed edges."""

    return _frozen.FrozenMapping(
        (name, _freeze_value(value, allow_value_ref=True, allow_payload=True))
        for name, value in values.items()
    )


def _freeze_value(
    value: object,
    *,
    allow_value_ref: bool,
    allow_payload: bool,
) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = "captured authoring numbers must be finite"
            raise ValueError(msg)
        return value
    if isinstance(value, Quantity):
        if not math.isfinite(value.value):
            msg = "captured authoring quantities must be finite"
            raise ValueError(msg)
        return value
    if isinstance(value, EntityRef):
        metadata = _frozen.freeze_json_mapping(value.metadata)
        return value.model_copy(update={"metadata": metadata})
    if isinstance(value, ValueRef) and allow_value_ref:
        return value
    if isinstance(value, PayloadValue) and allow_payload:
        return value.model_copy()
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return _frozen.FrozenMapping(
            (
                _runtime_mapping_key(name),
                _freeze_value(
                    item,
                    allow_value_ref=allow_value_ref,
                    allow_payload=allow_payload,
                ),
            )
            for name, item in mapping.items()
        )
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return tuple(
            _freeze_value(
                item,
                allow_value_ref=allow_value_ref,
                allow_payload=allow_payload,
            )
            for item in sequence
        )
    raise AssertionError(
        f"unsupported validated authoring value: {type(value).__name__}"
    )


def _runtime_mapping_key(value: object) -> str:
    if isinstance(value, str):
        return value
    msg = "runtime input object keys must be strings"
    raise TypeError(msg)


__all__ = [
    "empty_frozen_mapping",
    "freeze_module_inputs",
    "freeze_runtime_input",
    "freeze_runtime_inputs",
]
