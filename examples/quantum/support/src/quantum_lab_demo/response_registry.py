"""Program response selection for the deterministic fake quantum target."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from scopecat_quantum import authoring as quantum
from scopecat_quantum.program_targets import (
    PreparedQuantumTargetBatch,
    PreparedQuantumTargetEntry,
)

from quantum_lab_demo.point_values import QuantumLabPointValues
from quantum_lab_demo.targets.fake_list_mode import FakeAcquisitionResponse


@dataclass(frozen=True, slots=True)
class QuantumLabResponseRequest:
    """Target-local facts available to a deterministic response factory."""

    program: quantum.Program = field(repr=False)
    points: tuple[QuantumLabPointValues, ...]
    entries: tuple[PreparedQuantumTargetEntry, ...]
    batch: PreparedQuantumTargetBatch

    @property
    def shots(self) -> int:
        return self.batch.repetitions


type QuantumLabResponseFactory = Callable[
    [QuantumLabResponseRequest], FakeAcquisitionResponse
]


class QuantumLabResponseRegistry:
    """Select fake acquisition behavior independently of compilation policy."""

    def __init__(self, factories: Mapping[str, QuantumLabResponseFactory]) -> None:
        self._factories = dict(factories)

    def response_for(
        self,
        request: QuantumLabResponseRequest,
    ) -> FakeAcquisitionResponse | None:
        factory = self._factories.get(request.program.id)
        return None if factory is None else factory(request)


__all__ = [
    "QuantumLabResponseFactory",
    "QuantumLabResponseRegistry",
    "QuantumLabResponseRequest",
]
