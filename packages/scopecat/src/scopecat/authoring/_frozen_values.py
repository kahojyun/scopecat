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


def capture_runtime_input(value: object) -> object:
    """Validate and snapshot one closed runtime input."""

    return _capture_value(
        value,
        allow_value_ref=False,
        allow_payload=False,
        active_containers=set(),
        path="runtime input",
    )


def capture_runtime_inputs(
    values: Mapping[str, object],
) -> _frozen.FrozenMapping[str, object]:
    """Validate and snapshot a named set of closed runtime inputs."""

    return _capture_named_values(
        values,
        allow_value_ref=False,
        allow_payload=False,
        domain="runtime",
    )


def capture_module_inputs(
    values: Mapping[str, object],
) -> _frozen.FrozenMapping[str, object]:
    """Validate and snapshot module inputs while preserving typed edges."""

    return _capture_named_values(
        values,
        allow_value_ref=True,
        allow_payload=True,
        domain="module",
    )


def _capture_named_values(
    values: Mapping[str, object],
    *,
    allow_value_ref: bool,
    allow_payload: bool,
    domain: str,
) -> _frozen.FrozenMapping[str, object]:
    captured: list[tuple[str, object]] = []
    for name, value in cast("Mapping[object, object]", values).items():
        if not isinstance(name, str) or not name:
            msg = f"{domain} input names must be non-empty strings"
            raise TypeError(msg)
        captured.append(
            (
                name,
                _capture_value(
                    value,
                    allow_value_ref=allow_value_ref,
                    allow_payload=allow_payload,
                    active_containers=set(),
                    path=f"{domain} input {name!r}",
                ),
            )
        )
    return _frozen.FrozenMapping(captured)


def _capture_value(
    value: object,
    *,
    allow_value_ref: bool,
    allow_payload: bool,
    active_containers: set[int],
    path: str,
) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = f"{path} numbers must be finite"
            raise ValueError(msg)
        return value
    if isinstance(value, Quantity):
        if not math.isfinite(value.value):
            msg = f"{path} quantities must be finite"
            raise ValueError(msg)
        return value
    if isinstance(value, EntityRef):
        return value
    if isinstance(value, ValueRef) and allow_value_ref:
        return value
    if isinstance(value, PayloadValue) and allow_payload:
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        marker = _enter_container(mapping, active_containers, path=path)
        try:
            return _frozen.FrozenMapping(
                (
                    _runtime_mapping_key(name, path=path),
                    _capture_value(
                        item,
                        allow_value_ref=allow_value_ref,
                        allow_payload=allow_payload,
                        active_containers=active_containers,
                        path=f"{path}.{name}",
                    ),
                )
                for name, item in mapping.items()
            )
        finally:
            active_containers.remove(marker)
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        marker = _enter_container(sequence, active_containers, path=path)
        try:
            return tuple(
                _capture_value(
                    item,
                    allow_value_ref=allow_value_ref,
                    allow_payload=allow_payload,
                    active_containers=active_containers,
                    path=f"{path}[{index}]",
                )
                for index, item in enumerate(sequence)
            )
        finally:
            active_containers.remove(marker)
    policy = (
        "typed values or closed literal data"
        if allow_value_ref or allow_payload
        else "closed runtime data"
    )
    msg = f"{path} must be {policy}; got {type(value).__name__}"
    raise TypeError(msg)


def _enter_container(value: object, active_containers: set[int], *, path: str) -> int:
    marker = id(value)
    if marker in active_containers:
        msg = f"{path} contains a cycle"
        raise ValueError(msg)
    active_containers.add(marker)
    return marker


def _runtime_mapping_key(value: object, *, path: str) -> str:
    if isinstance(value, str):
        return value
    msg = f"{path} object keys must be strings"
    raise TypeError(msg)
