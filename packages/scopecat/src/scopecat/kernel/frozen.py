"""Small immutable containers for closed durable snapshots."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Never, TypeVar, cast, override

_K = TypeVar("_K")
_V = TypeVar("_V")


class FrozenMapping(Mapping[_K, _V]):
    """A serializable mapping whose contents cannot be mutated."""

    __slots__ = ("_values",)

    def __init__(self, values: Iterable[tuple[_K, _V]] = ()) -> None:
        self._values = MappingProxyType(dict(values))

    @override
    def __getitem__(self, key: _K) -> _V:
        return self._values[key]

    @override
    def __iter__(self) -> Iterator[_K]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    @override
    def __repr__(self) -> str:
        return repr(dict(self._values))

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False
        other_mapping = cast("Mapping[object, object]", other)
        return dict(self.items()) == dict(other_mapping.items())

    def __setitem__(self, _key: _K, _value: _V) -> Never:
        msg = "frozen mapping is immutable"
        raise TypeError(msg)

    def __delitem__(self, _key: _K) -> Never:
        msg = "frozen mapping is immutable"
        raise TypeError(msg)

    def __copy__(self) -> FrozenMapping[_K, _V]:
        return self

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> FrozenMapping[_K, _V]:
        return self


def empty_frozen_mapping[K, V]() -> FrozenMapping[K, V]:
    return FrozenMapping()


def freeze_json_mapping[T](
    values: Mapping[str, T],
    *,
    path: str = "metadata",
) -> FrozenMapping[str, T]:
    """Validate and recursively freeze a finite JSON-shaped mapping."""

    return cast(
        "FrozenMapping[str, T]",
        _freeze_json_mapping(
            cast("Mapping[object, object]", values),
            path=path,
            seen=set(),
        ),
    )


def thaw_json_value(value: object) -> object:
    """Return ordinary JSON containers for a recursively frozen value."""

    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        result: dict[str, object] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                msg = "frozen JSON mapping keys must be strings"
                raise ValueError(msg)
            result[key] = thaw_json_value(item)
        return result
    if isinstance(value, tuple):
        sequence = cast("tuple[object, ...]", value)
        return [thaw_json_value(item) for item in sequence]
    return value


def _freeze_json_mapping(
    values: Mapping[object, object],
    *,
    path: str,
    seen: set[int],
) -> FrozenMapping[str, object]:
    marker = id(values)
    if marker in seen:
        msg = f"{path} must not contain cycles"
        raise ValueError(msg)
    seen.add(marker)
    try:
        selected: list[tuple[str, object]] = []
        for key, item in values.items():
            if not isinstance(key, str):
                msg = f"{path} object keys must be strings"
                raise ValueError(msg)
            selected.append(
                (
                    key,
                    _freeze_json_value(
                        item,
                        path=f"{path}.{key}",
                        seen=seen,
                    ),
                )
            )
        return FrozenMapping(selected)
    finally:
        seen.remove(marker)


def _freeze_json_value(
    value: object,
    *,
    path: str,
    seen: set[int],
) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = f"{path} must be finite"
            raise ValueError(msg)
        return value
    if isinstance(value, Mapping):
        return _freeze_json_mapping(
            cast("Mapping[object, object]", value),
            path=path,
            seen=seen,
        )
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        marker = id(sequence)
        if marker in seen:
            msg = f"{path} must not contain cycles"
            raise ValueError(msg)
        seen.add(marker)
        try:
            return tuple(
                _freeze_json_value(
                    item,
                    path=f"{path}[{index}]",
                    seen=seen,
                )
                for index, item in enumerate(sequence)
            )
        finally:
            seen.remove(marker)
    msg = f"{path} must contain only durable JSON values"
    raise ValueError(msg)
