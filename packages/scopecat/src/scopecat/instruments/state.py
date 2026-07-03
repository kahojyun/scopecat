"""Instrument state and acquisition value objects."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.models.parameter import Quantity

StateValueKind = Literal["quantity", "number", "asset"]


class ExecutionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    coordinates: dict[str, Quantity]


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.execution_plan.v0"
    experiment_id: str
    coordinate_ids: list[str]
    points: list[ExecutionPoint]
    repeats: int = 1
    estimated_count: int


class StateValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: StateValueKind
    quantity: Quantity | None = None
    value: float | None = None
    asset_id: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> StateValue:
        if self.kind == "quantity":
            if self.quantity is None:
                msg = "quantity state value requires quantity"
                raise ValueError(msg)
            if self.value is not None:
                msg = "quantity state value cannot contain numeric value"
                raise ValueError(msg)
            if self.asset_id is not None:
                msg = "quantity state value cannot contain asset_id"
                raise ValueError(msg)
            return self
        if self.kind == "number":
            if self.value is None:
                msg = "number state value requires value"
                raise ValueError(msg)
            if self.quantity is not None:
                msg = "number state value cannot contain quantity"
                raise ValueError(msg)
            if self.asset_id is not None:
                msg = "number state value cannot contain asset_id"
                raise ValueError(msg)
            return self
        if self.kind == "asset":
            if not self.asset_id:
                msg = "asset state value requires asset_id"
                raise ValueError(msg)
            if self.quantity is not None or self.value is not None:
                msg = "asset state value cannot contain quantity or numeric value"
                raise ValueError(msg)
            return self
        msg = f"unsupported state value kind: {self.kind}"
        raise ValueError(msg)


class DesiredStateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    value: StateValue


class DesiredResourceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    capability_id: str
    fields: list[DesiredStateField]


class DesiredStatePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_index: int
    resources: list[DesiredResourceState]


class DesiredStatePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.desired_state_plan.v0"
    resource_ids: list[str]
    points: list[DesiredStatePoint]


class StatePatchField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    capability_id: str
    field_path: str
    before: StateValue | None = None
    after: StateValue


class StatePatchPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_index: int
    changed_fields: list[StatePatchField]


class StatePatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.state_patch_plan.v0"
    resource_ids: list[str]
    points: list[StatePatchPoint]
    total_changed_fields: int


class AcquisitionDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int | None = Field(default=None, ge=0)
    unit: str | None = None


class AcquisitionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.acquisition_plan.v0"
    kind: str
    record: Literal["point", "shot"]
    shots: int | None = Field(default=None, gt=0)
    repetitions: int | None = Field(default=None, gt=0)
    estimated_records: int = Field(ge=0)
    dimensions: list[AcquisitionDimension] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
