"""Instrument execution SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic
from scopecat.experiments import (
    ExperimentSpec,
    PlanSnapshot,
)
from scopecat.instruments.state import (
    AcquisitionPlan,
    DesiredResourceState,
    ExecutionPoint,
    StatePatchField,
    StateValue,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.provider import ProviderOptionDescription
from scopecat.results import MeasurementSink

CapabilityFieldKind = Literal["quantity", "number", "asset"]


class CapabilityField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: CapabilityFieldKind
    unit: str | None = None
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    fields: list[CapabilityField] = Field(default_factory=list)
    acquisition: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.instrument_description.v0"
    instrument_id: str
    implementation_id: str
    implementation_version: str
    capabilities: list[CapabilityDescription] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentStateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    field_path: str
    value: StateValue


class InstrumentStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.instrument_state_snapshot.v0"
    instrument_id: str
    fields: list[InstrumentStateField] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentStatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.instrument_state_patch.v0"
    instrument_id: str
    fields: list[StatePatchField] = Field(default_factory=list)


class InstrumentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostics: list[Diagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class AcquisitionContext:
    run_id: str
    plan: PlanSnapshot
    point: ExecutionPoint
    point_count: int
    record_index_offset: int
    records_for_point: int
    acquisition_plan: AcquisitionPlan | None
    desired_state: list[DesiredResourceState]


class Instrument(Protocol):
    instrument_id: str
    implementation_id: str
    implementation_version: str

    def describe(self) -> InstrumentDescription: ...

    def validate(self, desired: list[DesiredResourceState]) -> list[Diagnostic]: ...

    def readback(self) -> InstrumentStateSnapshot: ...

    def diff(
        self,
        current: InstrumentStateSnapshot,
        desired: list[DesiredResourceState],
    ) -> InstrumentStatePatch: ...

    def apply(self, patch: InstrumentStatePatch) -> InstrumentStateSnapshot: ...

    def acquire(
        self,
        context: AcquisitionContext,
        sink: MeasurementSink,
    ) -> InstrumentResult: ...

    def cleanup(self) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True)
class InstrumentProviderContext:
    config: ConfigProfileSnapshot
    experiment: ExperimentSpec


@dataclass(frozen=True)
class InstrumentProviderResult:
    instruments: tuple[Instrument, ...]
    diagnostics: tuple[Diagnostic, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InstrumentProviderDescription:
    provider_id: str
    label: str | None = None
    description: str | None = None
    options: tuple[ProviderOptionDescription, ...] = ()
    provided_instrument_ids: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class InstrumentProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def describe(self) -> InstrumentProviderDescription: ...

    def provide(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderResult: ...
