"""Concrete dispatch for point-local compute, state, and collection effects."""

from __future__ import annotations

from scopecat.execution.effects.compute import (
    ComputeEffectExecutor,
    PointEffectState,
)
from scopecat.execution.effects.measurement import MeasurementEffectExecutor
from scopecat.execution.effects.state import StateEffectExecutor
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    ComputeOperation,
    LocalOperation,
)


class PointEffectDispatcher:
    """Route one closed point-local operation to its concrete executor."""

    def __init__(
        self,
        *,
        compute: ComputeEffectExecutor,
        state: StateEffectExecutor,
        measurement: MeasurementEffectExecutor,
    ) -> None:
        self.compute = compute
        self.state = state
        self.measurement = measurement

    def execute(
        self,
        frame: PointEffectState,
        operation: LocalOperation,
    ) -> None:
        match operation:
            case ComputeOperation():
                self.compute.execute(frame, (operation,))
            case ApplyStateOperation():
                self.state.execute(frame, operation)
            case CollectOperation():
                self.measurement.execute(frame, operation)
