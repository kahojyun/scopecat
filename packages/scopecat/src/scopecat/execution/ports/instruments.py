"""Fenced instrument effects available to one admitted run."""

from __future__ import annotations

from typing import Literal, Protocol

from scopecat.kernel.problems import Problem
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentStateCommand,
)

type InstrumentLifecycleAction = Literal["cleanup", "abort", "close"]


class RunInstrumentHost(Protocol):
    """Control daemon-owned drivers without exposing driver objects to execution."""

    @property
    def provider_id(self) -> str | None: ...

    @property
    def descriptions(self) -> tuple[InstrumentDescription, ...]: ...

    @property
    def ready(self) -> bool: ...

    @property
    def setup_problems(self) -> tuple[Problem, ...]: ...

    def read_state(
        self,
        instrument_id: str,
        *,
        operation_id: str,
    ) -> InstrumentStateSnapshot: ...

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt: ...

    def collect(self, command: CollectCommand) -> CollectReceipt: ...

    def lifecycle(
        self,
        instrument_id: str,
        *,
        operation_id: str,
        action: InstrumentLifecycleAction,
    ) -> None: ...


__all__ = ["InstrumentLifecycleAction", "RunInstrumentHost"]
