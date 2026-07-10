"""Construction helpers for opaque frozen authoring handles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import MISSING, fields
from typing import cast


def create_handle[HandleT](
    handle_type: type[HandleT],
    /,
    **values: object,
) -> HandleT:
    """Initialize a dataclass handle without exposing its fields in ``__init__``."""

    descriptors = {
        descriptor.name: descriptor
        for descriptor in fields(handle_type)  # pyright: ignore[reportArgumentType]
    }
    unknown = sorted(set(values) - set(descriptors))
    if unknown:
        msg = "unknown opaque handle fields: " + ", ".join(unknown)
        raise TypeError(msg)
    result = object.__new__(handle_type)
    for name, descriptor in descriptors.items():
        if name in values:
            selected = values[name]
        elif descriptor.default is not MISSING:
            selected = descriptor.default
        elif descriptor.default_factory is not MISSING:
            factory = cast("Callable[[], object]", descriptor.default_factory)
            selected = factory()
        else:
            msg = f"missing opaque handle field: {name}"
            raise TypeError(msg)
        object.__setattr__(result, name, selected)
    post_init = getattr(result, "__post_init__", None)
    if callable(post_init):
        post_init()
    return result


def replace_handle[HandleT](value: HandleT, /, **changes: object) -> HandleT:
    """Return an updated immutable handle without calling its public constructor."""

    selected = {
        descriptor.name: getattr(value, descriptor.name)
        for descriptor in fields(value)  # pyright: ignore[reportArgumentType]
    }
    selected.update(changes)
    return create_handle(type(value), **selected)


__all__ = ["create_handle", "replace_handle"]
