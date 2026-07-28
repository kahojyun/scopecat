"""Daemon-owned hardware batches available to one admitted run."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.problems import Problem
from scopecat.records.artifact import CommandPayload
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.instruments.contracts import (
    CollectProductRequest,
    InstrumentDescription,
    InstrumentStateCommandField,
)


class _HardwareModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunHardwareApply(_HardwareModel):
    kind: Literal["apply"] = "apply"
    operation_id: str = Field(min_length=1)
    point_index: int = Field(ge=0)
    instrument_id: str = Field(min_length=1)
    fields: tuple[InstrumentStateCommandField, ...]
    payloads: dict[str, CommandPayload] = Field(default_factory=dict)


class RunHardwareCollectBinding(_HardwareModel):
    provider_key: str = Field(min_length=1)
    product_use_ids: tuple[str, ...] = Field(min_length=1)


class RunHardwareCollect(_HardwareModel):
    kind: Literal["collect"] = "collect"
    operation_id: str = Field(min_length=1)
    point_index: int = Field(ge=0)
    instrument_id: str = Field(min_length=1)
    point_count: int = Field(ge=1)
    requests: tuple[CollectProductRequest, ...] = ()
    bindings: tuple[RunHardwareCollectBinding, ...]

    @model_validator(mode="after")
    def validate_bindings(self) -> RunHardwareCollect:
        request_ids = {request.id for request in self.requests}
        binding_ids = {binding.provider_key for binding in self.bindings}
        if request_ids != binding_ids:
            raise ValueError("hardware collect bindings must match requested products")
        return self


type RunHardwareAction = Annotated[
    RunHardwareApply | RunHardwareCollect,
    Field(discriminator="kind"),
]


class RunHardwareBatch(_HardwareModel):
    operation_id: str = Field(min_length=1)
    actions: tuple[RunHardwareAction, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_operation_ids(self) -> RunHardwareBatch:
        operation_ids = [action.operation_id for action in self.actions]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("hardware batch action ids must be unique")
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
    def provider_id(self) -> str | None: ...

    @property
    def descriptions(self) -> tuple[InstrumentDescription, ...]: ...

    @property
    def ready(self) -> bool: ...

    @property
    def setup_problems(self) -> tuple[Problem, ...]: ...

    @property
    def initial_state(self) -> tuple[InstrumentStateSnapshot, ...]: ...

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
    "RunHardwareValue",
    "RunInstrumentHost",
]
