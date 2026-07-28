"""Daemon-owned hardware batches available to one admitted run."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.problems import Problem
from scopecat.records.artifact import CommandPayload
from scopecat.records.instrument import CommandChannelBinding, InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.instruments.contracts import (
    CollectResultRequest,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
    InvokeCommand,
)


class _HardwareModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunHardwareApply(_HardwareModel):
    kind: Literal["apply"] = "apply"
    effect_id: str = Field(min_length=1)
    point_index: int = Field(ge=0)
    instrument_id: str = Field(min_length=1)
    assignments: tuple[InstrumentStateAssignment, ...]


class RunHardwareInvoke(_HardwareModel):
    kind: Literal["invoke"] = "invoke"
    effect_id: str = Field(min_length=1)
    point_index: int = Field(ge=0)
    instrument_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    interface_id: InterfaceId
    component_path: tuple[str, ...] = ()
    operation_id: str = Field(min_length=1)
    arguments: tuple[InstrumentOperationArgument, ...] = ()
    payloads: dict[str, CommandPayload] = Field(default_factory=dict)
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    @model_validator(mode="after")
    def validate_command(self) -> RunHardwareInvoke:
        InvokeCommand(
            command_id=self.effect_id,
            instrument_id=self.instrument_id,
            resource_id=self.resource_id,
            interface_id=self.interface_id,
            component_path=list(self.component_path),
            operation_id=self.operation_id,
            arguments=list(self.arguments),
            payloads=self.payloads,
            entity_ids=list(self.entity_ids),
            channel_bindings=list(self.channel_bindings),
        )
        return self


class RunHardwareCollectBinding(_HardwareModel):
    request_id: str = Field(min_length=1)
    product_use_ids: tuple[str, ...] = Field(min_length=1)


class RunHardwareCollect(_HardwareModel):
    kind: Literal["collect"] = "collect"
    effect_id: str = Field(min_length=1)
    point_index: int = Field(ge=0)
    instrument_id: str = Field(min_length=1)
    point_count: int = Field(ge=1)
    requests: tuple[CollectResultRequest, ...] = ()
    bindings: tuple[RunHardwareCollectBinding, ...]

    @model_validator(mode="after")
    def validate_bindings(self) -> RunHardwareCollect:
        request_ids = {request.id for request in self.requests}
        binding_ids = {binding.request_id for binding in self.bindings}
        if request_ids != binding_ids:
            raise ValueError("hardware collect bindings must match requested results")
        return self


type RunHardwareAction = Annotated[
    RunHardwareApply | RunHardwareInvoke | RunHardwareCollect,
    Field(discriminator="kind"),
]


class RunHardwareBatch(_HardwareModel):
    operation_id: str = Field(min_length=1)
    actions: tuple[RunHardwareAction, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_effect_ids(self) -> RunHardwareBatch:
        effect_ids = [action.effect_id for action in self.actions]
        if len(effect_ids) != len(set(effect_ids)):
            raise ValueError("hardware batch effect ids must be unique")
        return self


class RunHardwareValue(_HardwareModel):
    point_index: int = Field(ge=0)
    product_use_id: str = Field(min_length=1)
    value: MeasurementValue


class RunHardwareBatchReceipt(_HardwareModel):
    operation_id: str = Field(min_length=1)
    values: tuple[RunHardwareValue, ...] = ()
    problems: tuple[Problem, ...] = ()
    indeterminate: bool = False


class RunHardwareFinalizationReceipt(_HardwareModel):
    operation_id: str = Field(min_length=1)
    final_state: tuple[InstrumentStateSnapshot, ...] = ()
    problems: tuple[Problem, ...] = ()
    indeterminate: bool = False


class RunInstrumentHost(Protocol):
    """Submit concrete hardware work without exposing daemon-owned drivers."""

    @property
    def ready(self) -> bool: ...

    @property
    def setup_problems(self) -> tuple[Problem, ...]: ...

    @property
    def observed_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        """Return fresh state read after the run acquired exclusive ownership."""
        ...

    @property
    def prepared_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        """Return the execution baseline after applying the run policy."""
        ...

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt: ...

    def finish(
        self,
        *,
        operation_id: str,
        failed: bool,
    ) -> RunHardwareFinalizationReceipt: ...


__all__ = [
    "RunHardwareAction",
    "RunHardwareApply",
    "RunHardwareBatch",
    "RunHardwareBatchReceipt",
    "RunHardwareCollect",
    "RunHardwareCollectBinding",
    "RunHardwareFinalizationReceipt",
    "RunHardwareInvoke",
    "RunHardwareValue",
    "RunInstrumentHost",
]
