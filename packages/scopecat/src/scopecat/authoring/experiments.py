"""Callable Python UX for immutable experiment invocations."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from scopecat.program.definitions import ExperimentInvocation

type ExperimentBuilder = Callable[[Mapping[str, object]], ExperimentInvocation]


@dataclass(frozen=True, slots=True, repr=False)
class Experiment[**P]:
    """One experiment authoring function with structural and runtime inputs."""

    _callable: Callable[P, object] = field(repr=False, compare=False)
    _signature: inspect.Signature = field(repr=False, compare=False)
    _builder: ExperimentBuilder = field(repr=False, compare=False)
    id: str
    kind: str
    metadata: Mapping[str, object] = field(repr=False)

    @property
    def __wrapped__(self) -> Callable[P, object]:
        return self._callable

    @property
    def __name__(self) -> str:
        return self._callable.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ExperimentInvocation:
        """Build one immutable invocation from structural and runtime arguments."""

        bound = self._signature.bind(*args, **kwargs)
        return self._builder(cast("Mapping[str, object]", bound.arguments))

    def bind(self, **inputs: object) -> ExperimentInvocation:
        """Build with complete structural args and partial runtime inputs."""

        bound = self._signature.bind_partial(**inputs)
        return self._builder(cast("Mapping[str, object]", bound.arguments))


__all__ = [
    "Experiment",
    "ExperimentInvocation",
]
