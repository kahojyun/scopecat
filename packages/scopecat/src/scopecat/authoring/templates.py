"""Callable Python UX for immutable experiment definitions."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from scopecat.program.definitions import (
    ExperimentDef,
    ExperimentInvocation,
    capture_experiment_inputs,
)
from scopecat.program.values import RuntimeInput
from scopecat.program.verification import validate_experiment_inputs


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentTemplate[**P]:
    """Callable UX for one canonical experiment definition."""

    definition: ExperimentDef
    _callable: Callable[P, object] = field(repr=False, compare=False)
    _signature: inspect.Signature = field(repr=False, compare=False)

    @property
    def __wrapped__(self) -> Callable[P, object]:
        return self._callable

    @property
    def __name__(self) -> str:
        return self._callable.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def bind(self, **inputs: object) -> ExperimentInvocation:
        """Partially bind named inputs; compilation checks completeness."""

        bound = self._signature.bind_partial(**inputs)
        return self._invocation(cast("dict[str, RuntimeInput]", dict(bound.arguments)))

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ExperimentInvocation:
        """Bind every required input through normal Python call semantics."""

        bound = self._signature.bind(*args, **kwargs)
        return self._invocation(cast("dict[str, RuntimeInput]", dict(bound.arguments)))

    def _invocation(
        self,
        inputs: Mapping[str, RuntimeInput],
    ) -> ExperimentInvocation:
        captured_inputs = capture_experiment_inputs(inputs)
        validate_experiment_inputs(
            definitions=self.definition.inputs,
            inputs=captured_inputs,
        )
        return ExperimentInvocation(
            definition=self.definition,
            inputs=captured_inputs,
            scans=(),
        )


__all__ = [
    "ExperimentInvocation",
    "ExperimentTemplate",
]
