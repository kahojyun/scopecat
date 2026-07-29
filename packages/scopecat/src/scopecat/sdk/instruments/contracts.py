"""Instrument driver SDK."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.units import compatible_units
from scopecat.kernel.value_type_wire import (
    InstrumentOperationScalarWire,
    InstrumentPropertyScalarWire,
)
from scopecat.kernel.value_types import Bool as BoolType
from scopecat.kernel.value_types import Float as FloatType
from scopecat.kernel.value_types import Int as IntType
from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_types import String as StringType
from scopecat.kernel.value_validation import (
    ValuePath,
    ValueValidationError,
    validate_literal,
)
from scopecat.measurements.contracts import (
    measurement_value_contract_issues,
)
from scopecat.measurements.results import MeasurementDType
from scopecat.records._metadata import JsonMetadata
from scopecat.records.artifact import CommandPayload
from scopecat.records.config import InstrumentBindingSpec
from scopecat.records.instrument import (
    CommandChannelBinding as _CommandChannelBinding,
)
from scopecat.records.instrument import (
    InstrumentPropertyState as _InstrumentPropertyState,
)
from scopecat.records.instrument import (
    InstrumentReadback as _InstrumentReadback,
)
from scopecat.records.instrument import (
    InstrumentStateSnapshot as _InstrumentStateSnapshot,
)
from scopecat.records.instrument import (
    StateTargetScopeIdentity as _StateTargetScopeIdentity,
)
from scopecat.records.instrument import (
    property_target_identity as _property_target_identity,
)
from scopecat.records.instrument import (
    property_target_sort_key as _property_target_sort_key,
)
from scopecat.records.instrument import (
    state_target_scope_identity as _state_target_scope_identity,
)
from scopecat.records.instrument import (
    validate_entity_target as _validate_entity_target,
)
from scopecat.records.measurement import MeasurementArray, MeasurementUnavailable
from scopecat.sdk.instruments._projection import (
    ProjectedInstrumentState as _ProjectedInstrumentState,
)
from scopecat.sdk.instruments.driver import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
)
from scopecat.sdk.problems import (
    LocationPathItem,
    Problem,
    ProblemPhase,
    model_location,
    problem,
)

type _NonEmptyId = Annotated[str, Field(min_length=1)]


class PropertySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    label: str | None = None
    description: str | None = None
    access: Literal["read_only", "write_only", "read_write"] = "read_write"
    value_type: InstrumentPropertyScalarWire

    @field_validator("value_type")
    @classmethod
    def validate_value_type(cls, value: Scalar) -> Scalar:
        return _validate_instrument_scalar(value, allow_payload=False)


class StateCaseSpec(BaseModel):
    """Properties available for one discriminator value."""

    model_config = ConfigDict(extra="forbid")

    value: _NonEmptyId
    property_ids: list[_NonEmptyId] = Field(default_factory=list)

    @field_validator("property_ids")
    @classmethod
    def validate_unique_properties(cls, value: list[str]) -> list[str]:
        _require_unique(value, "state case property ids")
        return value


class DiscriminatedStateSpec(BaseModel):
    """An exhaustive property partition selected by one persistent property."""

    model_config = ConfigDict(extra="forbid")

    discriminator_property_id: _NonEmptyId
    common_property_ids: list[_NonEmptyId] = Field(default_factory=list)
    cases: list[StateCaseSpec] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_partition_identity(self) -> DiscriminatedStateSpec:
        _require_unique(
            (case.value for case in self.cases),
            "state case values",
        )
        _require_unique(
            (
                self.discriminator_property_id,
                *self.common_property_ids,
                *(
                    property_id
                    for case in self.cases
                    for property_id in case.property_ids
                ),
            ),
            "discriminated state property ids",
        )
        return self


class AcquisitionAxisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    label: str | None = None
    description: str | None = None
    kind: _NonEmptyId
    size: int | None = None
    unit: str | None = None


class AcquisitionResultSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    label: str | None = None
    description: str | None = None
    dtype: MeasurementDType = "float64"
    unit: str | None = None
    axes: list[AcquisitionAxisSpec] = Field(default_factory=list)

    @field_validator("axes")
    @classmethod
    def validate_unique_axes(
        cls,
        value: list[AcquisitionAxisSpec],
    ) -> list[AcquisitionAxisSpec]:
        _require_unique(
            (axis.id for axis in value),
            "acquisition result axis ids",
        )
        return value

    @model_validator(mode="after")
    def validate_unitless_dtype(self) -> AcquisitionResultSpec:
        if self.dtype in {"bool", "string"} and self.unit is not None:
            raise ValueError(f"{self.dtype} acquisition results cannot have a unit")
        return self


class StateDiscriminatorRef(BaseModel):
    """Physical discriminator selecting one acquisition result case."""

    model_config = ConfigDict(extra="forbid")

    interface_id: InterfaceId
    component_path: list[_NonEmptyId] = Field(default_factory=list)
    property_id: _NonEmptyId


class AcquisitionCaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: _NonEmptyId
    results: list[AcquisitionResultSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_results(self) -> AcquisitionCaseSpec:
        _require_unique(
            (result.id for result in self.results),
            "acquisition case result ids",
        )
        return self


class OperationArgumentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    label: str | None = None
    description: str | None = None
    value_type: InstrumentOperationScalarWire

    @field_validator("value_type")
    @classmethod
    def validate_value_type(cls, value: Scalar) -> Scalar:
        return _validate_instrument_scalar(value, allow_payload=True)


class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    label: str | None = None
    description: str | None = None
    arguments: list[OperationArgumentSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_arguments(self) -> OperationSpec:
        _require_unique(
            (argument.id for argument in self.arguments),
            "operation argument ids",
        )
        return self


class _AcquisitionSpecBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    label: str | None = None
    description: str | None = None


class FixedAcquisitionSpec(_AcquisitionSpecBase):
    kind: Literal["fixed"] = "fixed"
    results: list[AcquisitionResultSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_results(self) -> FixedAcquisitionSpec:
        _require_unique(
            (result.id for result in self.results),
            "acquisition result ids",
        )
        return self


class StateDiscriminatedAcquisitionSpec(_AcquisitionSpecBase):
    kind: Literal["state_discriminated"] = "state_discriminated"
    discriminator: StateDiscriminatorRef
    cases: list[AcquisitionCaseSpec] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_cases(self) -> StateDiscriminatedAcquisitionSpec:
        _require_unique(
            (case.value for case in self.cases),
            "acquisition case values",
        )
        _require_unique(
            (result.id for case in self.cases for result in case.results),
            "state-discriminated acquisition result ids",
        )
        return self


type AcquisitionSpec = Annotated[
    FixedAcquisitionSpec | StateDiscriminatedAcquisitionSpec,
    Field(discriminator="kind"),
]


class ComponentSpec(BaseModel):
    """One stable role nested below an interface endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    label: str | None = None
    description: str | None = None
    properties: list[PropertySpec] = Field(default_factory=list)
    state: DiscriminatedStateSpec | None = None
    operations: list[OperationSpec] = Field(default_factory=list)
    acquisitions: list[AcquisitionSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_members(self) -> ComponentSpec:
        _validate_component_members(self)
        return self


class InterfaceSpec(BaseModel):
    """Versioned behavior contract implemented by an instrument endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: InterfaceId
    label: str | None = None
    description: str | None = None
    properties: list[PropertySpec] = Field(default_factory=list)
    state: DiscriminatedStateSpec | None = None
    operations: list[OperationSpec] = Field(default_factory=list)
    acquisitions: list[AcquisitionSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_members(self) -> InterfaceSpec:
        _validate_component_members(self)
        return self


class InstrumentDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    implementation_id: str
    implementation_version: str
    label: str | None = None
    description: str | None = None
    interfaces: list[InterfaceSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_interfaces(self) -> InstrumentDescription:
        _require_unique(
            (interface.id for interface in self.interfaces),
            "instrument interface ids",
        )
        _validate_acquisition_state_references(self)
        return self


class InstrumentStateAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    interface_id: InterfaceId
    component_path: list[_NonEmptyId] = Field(default_factory=list)
    property_id: _NonEmptyId
    value: StateValue
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[_CommandChannelBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> InstrumentStateAssignment:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


def _validate_payload_bindings(
    *,
    values: Iterable[StateValue],
    payloads: Mapping[str, CommandPayload],
    label: str,
) -> None:
    """Require one exact, self-consistent payload map for command values."""

    mismatched_keys = [
        (payload_id, payload.id)
        for payload_id, payload in payloads.items()
        if payload_id != payload.id
    ]
    if mismatched_keys:
        payload_id, descriptor_id = mismatched_keys[0]
        raise ValueError(
            f"{label} payload map key {payload_id!r} does not match "
            f"payload.id {descriptor_id!r}"
        )
    referenced_ids = {
        value.payload_id
        for item in values
        if isinstance((value := item.root), PayloadRef)
    }
    payload_ids = set(payloads)
    missing = sorted(referenced_ids - payload_ids)
    extra = sorted(payload_ids - referenced_ids)
    issues: list[str] = []
    if missing:
        issues.append(f"missing referenced payload ids: {missing!r}")
    if extra:
        issues.append(f"unreferenced payload ids: {extra!r}")
    if issues:
        raise ValueError(f"{label} payload map has " + "; ".join(issues))


class InstrumentStateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: _NonEmptyId
    instrument_id: _NonEmptyId
    assignments: list[InstrumentStateAssignment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_structure(self) -> InstrumentStateCommand:
        identities = [
            _property_target_identity(
                assignment.interface_id,
                assignment.component_path,
                assignment.property_id,
            )
            for assignment in self.assignments
        ]
        if len(identities) != len(set(identities)):
            msg = "instrument state command property targets must be unique"
            raise ValueError(msg)
        return self


class ApplyReceipt(BaseModel):
    """Outcome reported after one instrument state command.

    ``unknown`` is intentionally distinct from failure.  A driver can lose the
    response after the hardware accepted a command, so the execution engine must
    reconcile state before it can safely issue another command or retry.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["applied", "not_applied", "unknown"] = "applied"
    problems: tuple[Problem, ...] = ()
    state: _InstrumentStateSnapshot | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> ApplyReceipt:
        if self.status == "applied" and self.problems:
            msg = "an applied receipt cannot contain problems"
            raise ValueError(msg)
        if self.status != "applied" and not self.problems:
            msg = "a negative or unknown apply receipt requires a problem"
            raise ValueError(msg)
        return self


class CollectAxisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    kind: _NonEmptyId
    size: int = Field(gt=0)
    unit: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)


class CollectResultRequest(BaseModel):
    """One explicitly acquisition-scoped result request.

    Interface and acquisition identity prevent a driver from inferring
    ownership from an accidentally unique result id.
    """

    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    interface_id: InterfaceId
    component_path: list[_NonEmptyId] = Field(default_factory=list)
    acquisition_id: _NonEmptyId
    result_id: _NonEmptyId
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    dimensions: list[CollectAxisRequest] = Field(default_factory=list)
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[_CommandChannelBinding] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_target(self) -> CollectResultRequest:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        if self.dtype in {"bool", "string"} and self.unit is not None:
            raise ValueError(f"{self.dtype} collection results cannot have a unit")
        return self


class CollectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: _NonEmptyId
    instrument_id: _NonEmptyId
    point_index: int = Field(ge=0)
    point_count: int = Field(ge=1)
    requests: list[CollectResultRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_requests(self) -> CollectCommand:
        if self.point_index >= self.point_count:
            raise ValueError("collect command point index must be within point count")
        request_ids = [request.id for request in self.requests]
        if len(request_ids) != len(set(request_ids)):
            msg = "collect command request ids must be unique"
            raise ValueError(msg)
        acquisition_targets = {
            (
                request.interface_id,
                tuple(request.component_path),
                request.acquisition_id,
            )
            for request in self.requests
        }
        if len(acquisition_targets) != 1:
            raise ValueError("collect command must target exactly one acquisition")
        return self


class InstrumentOperationArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: _NonEmptyId
    value: StateValue


class InvokeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: _NonEmptyId
    instrument_id: _NonEmptyId
    resource_id: _NonEmptyId
    interface_id: InterfaceId
    component_path: list[_NonEmptyId] = Field(default_factory=list)
    operation_id: _NonEmptyId
    arguments: list[InstrumentOperationArgument] = Field(default_factory=list)
    payloads: dict[str, CommandPayload] = Field(default_factory=dict)
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[_CommandChannelBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structure(self) -> InvokeCommand:
        _require_unique(
            (argument.id for argument in self.arguments),
            "instrument operation argument ids",
        )
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        _validate_payload_bindings(
            values=(argument.value for argument in self.arguments),
            payloads=self.payloads,
            label="instrument invoke command",
        )
        return self


class InvokeReceipt(BaseModel):
    """Outcome reported after one atomic instrument operation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["invoked", "not_invoked", "unknown"] = "invoked"
    problems: tuple[Problem, ...] = ()
    state: _InstrumentStateSnapshot | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> InvokeReceipt:
        if self.status == "invoked" and self.problems:
            raise ValueError("an invoked receipt cannot contain problems")
        if self.status != "invoked" and not self.problems:
            raise ValueError("a negative or unknown invoke receipt requires a problem")
        return self


class CollectReceipt(BaseModel):
    """Explicit outcome reported after one collection command.

    ``not_collected`` proves that collection did not occur; ``unknown`` means it
    may have occurred. The distinction prevents automatic retry from silently
    duplicating an external acquisition.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["collected", "not_collected", "unknown"] = "collected"
    problems: tuple[Problem, ...] = ()
    readback: _InstrumentReadback | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_readback_outcome(self) -> CollectReceipt:
        if self.status == "collected" and self.readback is None:
            msg = "a collected receipt requires a readback"
            raise ValueError(msg)
        if self.status == "not_collected" and self.readback is not None:
            msg = "a not_collected receipt must not contain a readback"
            raise ValueError(msg)
        if self.status == "collected" and self.problems:
            msg = "a collected receipt cannot contain problems"
            raise ValueError(msg)
        if self.status != "collected" and not self.problems:
            msg = "a negative or unknown collect receipt requires a problem"
            raise ValueError(msg)
        return self


class DriverFault(Exception):
    """Exceptional driver control flow carrying one stable public problem."""

    def __init__(self, problem: Problem) -> None:
        self.problem = problem
        super().__init__(problem.message)


class InstrumentDriver(Protocol):
    implementation_id: str
    implementation_version: str

    @property
    def instrument_id(self) -> str: ...

    def describe(self) -> InstrumentDescription: ...

    def read_state(self) -> _InstrumentStateSnapshot: ...

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt: ...

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt: ...

    def collect(self, request: DriverCollectRequest) -> CollectReceipt: ...

    def disconnect(self) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True, slots=True)
class InstrumentProviderContext:
    """Inputs for side-effect-free catalog discovery."""

    bindings: tuple[InstrumentBindingSpec, ...]


@dataclass(frozen=True, slots=True)
class InstrumentConnectionContext:
    """Inputs for opening one driver for exactly one configured instrument."""

    binding: InstrumentBindingSpec


@dataclass(frozen=True)
class InstrumentProviderDescription:
    """Pure, binding-specific declaration of instruments a provider can create."""

    provider_id: str
    instruments: tuple[InstrumentDescription, ...] = ()
    problems: tuple[Problem, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id:
            msg = "instrument provider id must be non-empty"
            raise ValueError(msg)
        validate_instrument_description_collection(self.instruments)


class InstrumentProvider(Protocol):
    """Pure catalog plus a one-instrument driver connection boundary.

    ``connect`` returns a fresh identified driver; expected rejections raise
    ``DriverFault``.
    """

    @property
    def provider_id(self) -> str: ...

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription: ...

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver: ...


def state_case(
    value: str,
    *,
    property_ids: list[str] | tuple[str, ...] = (),
) -> StateCaseSpec:
    return StateCaseSpec(
        value=value,
        property_ids=list(property_ids),
    )


def discriminated_state(
    discriminator_property_id: str,
    *,
    common_property_ids: list[str] | tuple[str, ...] = (),
    cases: list[StateCaseSpec] | tuple[StateCaseSpec, ...],
) -> DiscriminatedStateSpec:
    return DiscriminatedStateSpec(
        discriminator_property_id=discriminator_property_id,
        common_property_ids=list(common_property_ids),
        cases=list(cases),
    )


def interface(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    properties: list[PropertySpec] | tuple[PropertySpec, ...] = (),
    state: DiscriminatedStateSpec | None = None,
    operations: list[OperationSpec] | tuple[OperationSpec, ...] = (),
    acquisitions: list[AcquisitionSpec] | tuple[AcquisitionSpec, ...] = (),
    components: list[ComponentSpec] | tuple[ComponentSpec, ...] = (),
) -> InterfaceSpec:
    return InterfaceSpec(
        id=id,
        label=label,
        description=description,
        properties=list(properties),
        state=state,
        operations=list(operations),
        acquisitions=list(acquisitions),
        components=list(components),
    )


def component(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    properties: list[PropertySpec] | tuple[PropertySpec, ...] = (),
    state: DiscriminatedStateSpec | None = None,
    operations: list[OperationSpec] | tuple[OperationSpec, ...] = (),
    acquisitions: list[AcquisitionSpec] | tuple[AcquisitionSpec, ...] = (),
    components: list[ComponentSpec] | tuple[ComponentSpec, ...] = (),
) -> ComponentSpec:
    return ComponentSpec(
        id=id,
        label=label,
        description=description,
        properties=list(properties),
        state=state,
        operations=list(operations),
        acquisitions=list(acquisitions),
        components=list(components),
    )


def acquisition_axis(
    id: str,
    *,
    size: int | None = None,
    kind: str | None = None,
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> AcquisitionAxisSpec:
    return AcquisitionAxisSpec(
        id=id,
        label=label,
        description=description,
        kind=kind or id,
        size=size,
        unit=unit,
    )


def acquisition_result(
    id: str,
    *,
    dtype: MeasurementDType = "float64",
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
    axes: list[AcquisitionAxisSpec] | tuple[AcquisitionAxisSpec, ...] = (),
) -> AcquisitionResultSpec:
    return AcquisitionResultSpec(
        id=id,
        label=label,
        description=description,
        dtype=dtype,
        unit=unit,
        axes=list(axes),
    )


def acquisition(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    results: (list[AcquisitionResultSpec] | tuple[AcquisitionResultSpec, ...]) = (),
) -> FixedAcquisitionSpec:
    return FixedAcquisitionSpec(
        id=id,
        label=label,
        description=description,
        results=list(results),
    )


def state_discriminator_ref(
    interface_id: str,
    property_id: str,
    *,
    component_path: list[str] | tuple[str, ...] = (),
) -> StateDiscriminatorRef:
    return StateDiscriminatorRef(
        interface_id=interface_id,
        component_path=list(component_path),
        property_id=property_id,
    )


def acquisition_case(
    value: str,
    *,
    results: list[AcquisitionResultSpec] | tuple[AcquisitionResultSpec, ...],
) -> AcquisitionCaseSpec:
    return AcquisitionCaseSpec(value=value, results=list(results))


def state_discriminated_acquisition(
    id: str,
    *,
    discriminator: StateDiscriminatorRef,
    cases: list[AcquisitionCaseSpec] | tuple[AcquisitionCaseSpec, ...],
    label: str | None = None,
    description: str | None = None,
) -> StateDiscriminatedAcquisitionSpec:
    return StateDiscriminatedAcquisitionSpec(
        id=id,
        label=label,
        description=description,
        discriminator=discriminator,
        cases=list(cases),
    )


def acquisition_results(
    acquisition_spec: AcquisitionSpec,
) -> tuple[AcquisitionResultSpec, ...]:
    if isinstance(acquisition_spec, FixedAcquisitionSpec):
        return tuple(acquisition_spec.results)
    return tuple(result for case in acquisition_spec.cases for result in case.results)


def operation_argument(
    id: str,
    *,
    value_type: InstrumentOperationScalarWire,
    label: str | None = None,
    description: str | None = None,
) -> OperationArgumentSpec:
    return OperationArgumentSpec(
        id=id,
        label=label,
        description=description,
        value_type=value_type,
    )


def operation(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    arguments: (list[OperationArgumentSpec] | tuple[OperationArgumentSpec, ...]) = (),
) -> OperationSpec:
    return OperationSpec(
        id=id,
        label=label,
        description=description,
        arguments=list(arguments),
    )


def quantity_property(
    id: str,
    *,
    unit: str,
    minimum: float | None = None,
    maximum: float | None = None,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> PropertySpec:
    return PropertySpec(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(
            QuantityType(
                unit=unit,
                minimum=minimum,
                maximum=maximum,
            )
        ),
    )


def bool_property(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> PropertySpec:
    return PropertySpec(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(BoolType()),
    )


def int_property(
    id: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> PropertySpec:
    return PropertySpec(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(IntType(minimum=minimum, maximum=maximum)),
    )


def float_property(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> PropertySpec:
    return PropertySpec(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(FloatType()),
    )


def string_property(
    id: str,
    *,
    choices: tuple[str, ...] | None = None,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> PropertySpec:
    return PropertySpec(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(StringType(choices=choices)),
    )


def enum_property(
    id: str,
    *,
    choices: tuple[str, ...],
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> PropertySpec:
    return string_property(
        id,
        choices=choices,
        label=label,
        description=description,
        access=access,
    )


def validate_state_command(
    *,
    command: InstrumentStateCommand,
    description: InstrumentDescription,
    baseline: _InstrumentStateSnapshot | _ProjectedInstrumentState | None = None,
    require_explicit_state_case: bool = False,
) -> list[Problem]:
    """Validate one structurally complete command against a driver contract."""

    return validate_state_assignments(
        instrument_id=command.instrument_id,
        assignments=command.assignments,
        description=description,
        baseline=baseline,
        require_explicit_state_case=require_explicit_state_case,
    )


def validate_state_assignments(
    *,
    instrument_id: str,
    assignments: Sequence[InstrumentStateAssignment],
    description: InstrumentDescription,
    baseline: _InstrumentStateSnapshot | _ProjectedInstrumentState | None = None,
    require_explicit_state_case: bool = False,
) -> list[Problem]:
    """Validate persistent property assignments against one driver contract."""

    return _validate_state_assignments(
        instrument_id=instrument_id,
        assignments=assignments,
        description=description,
        baseline=baseline,
        require_observable=False,
        require_explicit_state_case=require_explicit_state_case,
    )


def validate_reconciled_state_assignments(
    *,
    instrument_id: str,
    assignments: Sequence[InstrumentStateAssignment],
    description: InstrumentDescription,
    baseline: _InstrumentStateSnapshot | _ProjectedInstrumentState | None = None,
    require_explicit_state_case: bool = False,
) -> list[Problem]:
    """Validate desired state that must be observable after it is applied."""

    return _validate_state_assignments(
        instrument_id=instrument_id,
        assignments=assignments,
        description=description,
        baseline=baseline,
        require_observable=True,
        require_explicit_state_case=require_explicit_state_case,
    )


def _validate_state_assignments(
    *,
    instrument_id: str,
    assignments: Sequence[InstrumentStateAssignment],
    description: InstrumentDescription,
    baseline: _InstrumentStateSnapshot | _ProjectedInstrumentState | None,
    require_observable: bool,
    require_explicit_state_case: bool,
) -> list[Problem]:
    problems: list[Problem] = []
    if instrument_id != description.instrument_id:
        problems.append(
            _problem(
                "instrument_driver_mismatch",
                f"{description.instrument_id} cannot apply command for {instrument_id}",
                "instrument_id",
            )
        )
        return problems
    if baseline is not None and baseline.instrument_id != instrument_id:
        problems.append(
            _problem(
                "instrument_driver_baseline_mismatch",
                f"{instrument_id} cannot use state observed from "
                f"{baseline.instrument_id}",
                "baseline",
                "instrument_id",
            )
        )
        return problems
    if isinstance(baseline, _InstrumentStateSnapshot):
        baseline_problems = validate_state_snapshot(
            snapshot=baseline,
            description=description,
        )
        if baseline_problems:
            return baseline_problems
    interfaces = {interface.id: interface for interface in description.interfaces}
    grouped: dict[
        _StateTargetScopeIdentity,
        tuple[InterfaceSpec | ComponentSpec, list[InstrumentStateAssignment]],
    ] = {}
    for assignment in assignments:
        if assignment.resource_id != instrument_id:
            problems.append(
                _problem(
                    "instrument_driver_resource_mismatch",
                    f"{instrument_id} cannot control {assignment.resource_id}",
                    "resource_id",
                )
            )
            continue
        interface_spec = interfaces.get(assignment.interface_id)
        if interface_spec is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_interface",
                    f"{instrument_id} does not support {assignment.interface_id}",
                    "interface_id",
                )
            )
            continue
        component_spec = _resolve_component(
            interface_spec,
            assignment.component_path,
        )
        if component_spec is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_component",
                    f"{instrument_id} does not support component "
                    f"{'/'.join(assignment.component_path)!r} under "
                    f"{assignment.interface_id}",
                    "component_path",
                )
            )
            continue
        property_spec = next(
            (
                item
                for item in component_spec.properties
                if item.id == assignment.property_id
            ),
            None,
        )
        if property_spec is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_property",
                    f"{instrument_id} does not support {assignment.property_id}",
                    "property_id",
                )
            )
            continue
        scope = _state_target_scope_identity(
            assignment.interface_id,
            assignment.component_path,
        )
        grouped.setdefault(scope, (component_spec, []))[1].append(assignment)
        if property_spec.access == "read_only":
            problems.append(
                _problem(
                    "instrument_driver_read_only_property",
                    f"{instrument_id} property {assignment.property_id} is read-only",
                    "property_id",
                )
            )
            continue
        if require_observable and property_spec.access == "write_only":
            problems.append(
                _problem(
                    "instrument_driver_write_only_property",
                    f"{instrument_id} property {assignment.property_id} "
                    "is write-only and cannot be reconciled",
                    "property_id",
                )
            )
            continue
        problems.extend(
            _validate_state_value(
                property_id=assignment.property_id,
                value=assignment.value,
                spec=property_spec,
            )
        )
    baseline_by_scope = (
        _state_properties_by_scope(baseline) if baseline is not None else {}
    )
    for scope, (component_spec, scoped_assignments) in grouped.items():
        problems.extend(
            _validate_state_case_assignments(
                scoped_assignments,
                component_spec,
                baseline_properties=(
                    baseline_by_scope.get(scope, ()) if baseline is not None else None
                ),
                require_explicit_state_case=require_explicit_state_case,
            )
        )
    return problems


def validate_state_snapshot(
    *,
    snapshot: _InstrumentStateSnapshot,
    description: InstrumentDescription,
) -> list[Problem]:
    """Validate observed persistent state against its advertised interface."""

    if snapshot.instrument_id != description.instrument_id:
        return [
            _snapshot_problem(
                "instrument_driver_snapshot_mismatch",
                f"{description.instrument_id} returned state for "
                f"{snapshot.instrument_id}",
                "instrument_id",
            )
        ]
    interfaces = {interface.id: interface for interface in description.interfaces}
    grouped: dict[
        _StateTargetScopeIdentity,
        tuple[InterfaceSpec | ComponentSpec, list[_InstrumentPropertyState]],
    ] = {
        scope: (component_spec, [])
        for scope, component_spec in _static_observable_state_scopes(description)
    }
    problems: list[Problem] = []
    for property_state in snapshot.properties:
        interface_spec = interfaces.get(property_state.interface_id)
        if interface_spec is None:
            problems.append(
                _snapshot_problem(
                    "instrument_driver_snapshot_unsupported_interface",
                    f"{snapshot.instrument_id} returned unsupported interface "
                    f"{property_state.interface_id}",
                    "properties",
                    property_state.property_id,
                    "interface_id",
                )
            )
            continue
        component_spec = _resolve_component(
            interface_spec,
            property_state.component_path,
        )
        if component_spec is None:
            problems.append(
                _snapshot_problem(
                    "instrument_driver_snapshot_unsupported_component",
                    f"{snapshot.instrument_id} returned unsupported component "
                    f"{'/'.join(property_state.component_path)!r}",
                    "properties",
                    property_state.property_id,
                    "component_path",
                )
            )
            continue
        property_spec = next(
            (
                item
                for item in component_spec.properties
                if item.id == property_state.property_id
            ),
            None,
        )
        if property_spec is None:
            problems.append(
                _snapshot_problem(
                    "instrument_driver_snapshot_unsupported_property",
                    f"{snapshot.instrument_id} returned unsupported property "
                    f"{property_state.property_id}",
                    "properties",
                    property_state.property_id,
                )
            )
            continue
        scope = _state_target_scope_identity(
            property_state.interface_id,
            property_state.component_path,
        )
        grouped.setdefault(scope, (component_spec, []))[1].append(property_state)
        if property_spec.access == "write_only":
            problems.append(
                _snapshot_problem(
                    "instrument_driver_snapshot_write_only_property",
                    f"{snapshot.instrument_id} returned write-only property "
                    f"{property_state.property_id}",
                    "properties",
                    property_state.property_id,
                )
            )
            continue
        try:
            validate_literal(
                property_spec.value_type,
                property_state.value.root,
                path=("value",),
            )
        except ValueValidationError as error:
            problems.append(
                _snapshot_problem(
                    "instrument_driver_snapshot_property_value_mismatch",
                    f"{property_state.property_id}: {error.reason}",
                    "properties",
                    property_state.property_id,
                    *error.path,
                )
            )
    for scope, (component_spec, scoped_properties) in grouped.items():
        problems.extend(
            _validate_snapshot_scope(
                scoped_properties,
                component_spec,
                scope=scope,
            )
        )
    return problems


def validate_invoke_command(
    *,
    command: InvokeCommand,
    description: InstrumentDescription,
) -> list[Problem]:
    """Validate one atomic operation invocation against a driver contract."""

    if command.instrument_id != description.instrument_id:
        return [
            _problem(
                "instrument_driver_mismatch",
                f"{description.instrument_id} cannot invoke for "
                f"{command.instrument_id}",
                "instrument_id",
            )
        ]
    if command.resource_id != command.instrument_id:
        return [
            _problem(
                "instrument_driver_resource_mismatch",
                f"{command.instrument_id} cannot control {command.resource_id}",
                "resource_id",
            )
        ]
    interface_spec = next(
        (
            interface
            for interface in description.interfaces
            if interface.id == command.interface_id
        ),
        None,
    )
    if interface_spec is None:
        return [
            _problem(
                "instrument_driver_unsupported_interface",
                f"{command.instrument_id} does not support {command.interface_id}",
                "interface_id",
            )
        ]
    component_spec = _resolve_component(interface_spec, command.component_path)
    if component_spec is None:
        return [
            _problem(
                "instrument_driver_unsupported_component",
                f"{command.instrument_id} does not support component "
                f"{'/'.join(command.component_path)!r} under {command.interface_id}",
                "component_path",
            )
        ]
    operation_spec = next(
        (
            operation
            for operation in component_spec.operations
            if operation.id == command.operation_id
        ),
        None,
    )
    if operation_spec is None:
        return [
            _problem(
                "instrument_driver_unsupported_operation",
                f"{command.instrument_id} does not support operation "
                f"{command.operation_id} under {command.interface_id}",
                "operation_id",
            )
        ]

    declared = {argument.id: argument for argument in operation_spec.arguments}
    supplied = {argument.id: argument for argument in command.arguments}
    problems: list[Problem] = []
    for argument_id in sorted(declared.keys() - supplied.keys()):
        problems.append(
            _problem(
                "instrument_driver_missing_operation_argument",
                f"{command.instrument_id} operation {command.operation_id} "
                f"requires argument {argument_id}",
                "arguments",
                argument_id,
            )
        )
    for argument_id in sorted(supplied.keys() - declared.keys()):
        problems.append(
            _problem(
                "instrument_driver_unsupported_operation_argument",
                f"{command.instrument_id} operation {command.operation_id} "
                f"does not accept argument {argument_id}",
                "arguments",
                argument_id,
            )
        )
    payload_schemas = {
        payload_id: payload.schema_id
        for payload_id, payload in command.payloads.items()
    }
    for argument_id in sorted(declared.keys() & supplied.keys()):
        problems.extend(
            _validate_operation_argument(
                argument_id=argument_id,
                value=supplied[argument_id].value,
                spec=declared[argument_id],
                payload_schemas=payload_schemas,
            )
        )
    return problems


def _active_acquisition_results(
    *,
    command: CollectCommand,
    request: CollectResultRequest,
    acquisition_spec: AcquisitionSpec,
    description: InstrumentDescription,
    baseline: _InstrumentStateSnapshot | _ProjectedInstrumentState | None,
) -> tuple[str | None, frozenset[str], Problem | None]:
    if isinstance(acquisition_spec, FixedAcquisitionSpec):
        return (
            None,
            frozenset(result.id for result in acquisition_results(acquisition_spec)),
            None,
        )
    if baseline is not None and baseline.instrument_id == command.instrument_id:
        baseline_is_usable = isinstance(
            baseline, _ProjectedInstrumentState
        ) or not validate_state_snapshot(
            snapshot=baseline,
            description=description,
        )
        if baseline_is_usable:
            reference = acquisition_spec.discriminator
            identity = _property_target_identity(
                reference.interface_id,
                reference.component_path,
                reference.property_id,
            )
            discriminator = next(
                (
                    property_state.value.root
                    for property_state in baseline.properties
                    if _property_target_identity(
                        property_state.interface_id,
                        property_state.component_path,
                        property_state.property_id,
                    )
                    == identity
                ),
                None,
            )
            if isinstance(discriminator, str):
                selected_case = next(
                    (
                        case
                        for case in acquisition_spec.cases
                        if case.value == discriminator
                    ),
                    None,
                )
                if selected_case is not None:
                    return (
                        discriminator,
                        frozenset(result.id for result in selected_case.results),
                        None,
                    )
    return (
        None,
        frozenset(),
        _problem(
            "instrument_driver_acquisition_state_unknown",
            f"{command.instrument_id} acquisition {request.acquisition_id} "
            "requires a complete observed discriminator state",
            "requests",
            request.id,
            "acquisition_id",
        ),
    )


def validate_collect_command(
    *,
    command: CollectCommand,
    description: InstrumentDescription,
    baseline: _InstrumentStateSnapshot | _ProjectedInstrumentState | None = None,
) -> list[Problem]:
    """Validate direct acquisition ownership before invoking a live driver."""

    if command.instrument_id != description.instrument_id:
        return [
            _problem(
                "instrument_driver_mismatch",
                f"{description.instrument_id} cannot collect for "
                f"{command.instrument_id}",
                "instrument_id",
            )
        ]
    request_target = command.requests[0]
    interface_spec = next(
        (
            interface
            for interface in description.interfaces
            if interface.id == request_target.interface_id
        ),
        None,
    )
    if interface_spec is None:
        return [
            _problem(
                "instrument_driver_unsupported_interface",
                f"{command.instrument_id} does not support "
                f"{request_target.interface_id}",
                "requests",
                request_target.id,
                "interface_id",
            )
        ]
    component_spec = _resolve_component(
        interface_spec,
        request_target.component_path,
    )
    if component_spec is None:
        return [
            _problem(
                "instrument_driver_unsupported_component",
                f"{command.instrument_id} does not support component "
                f"{'/'.join(request_target.component_path)!r}",
                "requests",
                request_target.id,
                "component_path",
            )
        ]
    acquisition_spec = next(
        (
            acquisition
            for acquisition in component_spec.acquisitions
            if acquisition.id == request_target.acquisition_id
        ),
        None,
    )
    if acquisition_spec is None:
        return [
            _problem(
                "instrument_driver_unsupported_acquisition",
                f"{command.instrument_id} does not support acquisition "
                f"{request_target.acquisition_id} under "
                f"{request_target.interface_id}",
                "requests",
                request_target.id,
                "acquisition_id",
            )
        ]
    declared_results = {
        result.id: result for result in acquisition_results(acquisition_spec)
    }
    unsupported_results = [
        _problem(
            "instrument_driver_unsupported_acquisition_result",
            f"{command.instrument_id} acquisition "
            f"{request.acquisition_id} has no result {request.result_id}",
            "requests",
            request.id,
            "result_id",
        )
        for request in command.requests
        if request.result_id not in declared_results
    ]
    if unsupported_results:
        return unsupported_results
    active_case, active_result_ids, state_problem = _active_acquisition_results(
        command=command,
        request=request_target,
        acquisition_spec=acquisition_spec,
        description=description,
        baseline=baseline,
    )
    if state_problem is not None:
        return [state_problem]

    problems: list[Problem] = []
    for request in command.requests:
        result_spec = declared_results[request.result_id]
        if request.result_id not in active_result_ids:
            problems.append(
                _problem(
                    "instrument_driver_inactive_acquisition_result",
                    f"{command.instrument_id} acquisition "
                    f"{request.acquisition_id} result {request.result_id} "
                    f"is inactive in state case {active_case!r}",
                    "requests",
                    request.id,
                    "result_id",
                )
            )
            continue
        if request.dtype != result_spec.dtype:
            problems.append(
                _problem(
                    "instrument_driver_acquisition_dtype_mismatch",
                    f"{command.instrument_id} acquisition result "
                    f"{request.result_id} requires dtype {result_spec.dtype}, "
                    f"got {request.dtype}",
                    "requests",
                    request.id,
                    "dtype",
                )
            )
        requested_unit = request.unit
        if requested_unit is not None and (
            result_spec.unit is None
            or not compatible_units(requested_unit, result_spec.unit)
        ):
            problems.append(
                _problem(
                    "instrument_driver_acquisition_unit_mismatch",
                    f"{command.instrument_id} acquisition result "
                    f"{request.result_id} requires unit compatible with "
                    f"{result_spec.unit!r}, got "
                    f"{requested_unit!r}",
                    "requests",
                    request.id,
                    "unit",
                )
            )
        dimensions = request.dimensions
        dynamic_unspecified = (
            not dimensions
            and bool(result_spec.axes)
            and all(axis.size is None for axis in result_spec.axes)
        )
        if dynamic_unspecified:
            continue
        if len(dimensions) != len(result_spec.axes):
            problems.append(
                _problem(
                    "instrument_driver_acquisition_axes_mismatch",
                    f"{command.instrument_id} acquisition result "
                    f"{request.result_id} axes do not "
                    "match its declared contract",
                    "requests",
                    request.id,
                    "dimensions",
                )
            )
            continue
        for axis_index, (requested_axis, declared_axis) in enumerate(
            zip(dimensions, result_spec.axes, strict=True)
        ):
            if (
                requested_axis.id != declared_axis.id
                or requested_axis.kind != declared_axis.kind
                or (
                    declared_axis.size is not None
                    and requested_axis.size != declared_axis.size
                )
            ):
                problems.append(
                    _problem(
                        "instrument_driver_acquisition_axis_mismatch",
                        f"{command.instrument_id} acquisition result "
                        f"{request.result_id} axis "
                        f"{declared_axis.id} does not match its declared contract",
                        "requests",
                        request.id,
                        "dimensions",
                        axis_index,
                    )
                )
            requested_axis_unit = requested_axis.unit
            if requested_axis_unit is not None and (
                declared_axis.unit is None
                or not compatible_units(requested_axis_unit, declared_axis.unit)
            ):
                problems.append(
                    _problem(
                        "instrument_driver_acquisition_axis_unit_mismatch",
                        f"{command.instrument_id} acquisition result "
                        f"{request.result_id} axis "
                        f"{declared_axis.id} requires a unit compatible with "
                        f"{declared_axis.unit!r}, got {requested_axis_unit!r}",
                        "requests",
                        request.id,
                        "dimensions",
                        axis_index,
                        "unit",
                    )
                )
    return problems


def validate_collect_receipt(
    *,
    command: CollectCommand,
    receipt: CollectReceipt,
) -> list[Problem]:
    """Validate direct collection data without imposing an unspecified shape."""

    if receipt.status != "collected":
        return []
    assert receipt.readback is not None
    requests = {request.id: request for request in command.requests}
    values = receipt.readback.values
    problems: list[Problem] = []
    for request_id in sorted(set(requests) - set(values)):
        problems.append(
            _problem(
                "instrument_driver_missing_acquisition_result",
                f"{command.instrument_id} did not return acquisition request "
                f"{request_id}",
                "readback",
                "values",
                request_id,
            )
        )
    for request_id in sorted(set(values) - set(requests)):
        problems.append(
            _problem(
                "instrument_driver_unexpected_acquisition_result",
                f"{command.instrument_id} returned unexpected acquisition request "
                f"{request_id}",
                "readback",
                "values",
                request_id,
            )
        )
    for request_id in sorted(set(requests) & set(values)):
        request = requests[request_id]
        value = values[request_id]
        expected_shape = (
            tuple(axis.size for axis in request.dimensions)
            if request.dimensions
            else (
                tuple(value.shape)
                if isinstance(value, MeasurementArray | MeasurementUnavailable)
                else ()
            )
        )
        for issue in measurement_value_contract_issues(
            value,
            expected_dtype=request.dtype,
            expected_unit=request.unit,
            expected_shape=expected_shape,
        ):
            problems.append(
                _problem(
                    f"instrument_driver_readback_{issue.code.value}",
                    f"{command.instrument_id} acquisition request "
                    f"{request_id} violates "
                    f"its requested {issue.code.value} contract",
                    "readback",
                    "values",
                    request_id,
                    *issue.path,
                )
            )
    return problems


def project_instrument_state(
    state: _InstrumentStateSnapshot | _ProjectedInstrumentState,
    command: InstrumentStateCommand,
    *,
    description: InstrumentDescription,
) -> _ProjectedInstrumentState:
    """Project preflight knowledge without claiming a hardware observation."""

    properties = {
        _property_target_identity(
            item.interface_id,
            item.component_path,
            item.property_id,
        ): item.model_copy(deep=True)
        for item in state.properties
    }
    assignments_by_scope: dict[
        _StateTargetScopeIdentity,
        list[InstrumentStateAssignment],
    ] = {}
    for assignment in command.assignments:
        scope = _state_target_scope_identity(
            assignment.interface_id,
            assignment.component_path,
        )
        assignments_by_scope.setdefault(scope, []).append(assignment)
    interfaces = {interface.id: interface for interface in description.interfaces}
    for scope, assignments in assignments_by_scope.items():
        interface_spec = interfaces.get(scope[0])
        if interface_spec is None:
            continue
        component_spec = _resolve_component(interface_spec, scope[1])
        if component_spec is None or component_spec.state is None:
            continue
        state_spec = component_spec.state
        discriminator = next(
            (
                assignment
                for assignment in assignments
                if assignment.property_id == state_spec.discriminator_property_id
            ),
            None,
        )
        if discriminator is None or not isinstance(discriminator.value.root, str):
            continue
        current = next(
            (
                item
                for item in properties.values()
                if _state_target_scope_identity(
                    item.interface_id,
                    item.component_path,
                )
                == scope
                and item.property_id == state_spec.discriminator_property_id
            ),
            None,
        )
        if current is not None and current.value.root == discriminator.value.root:
            continue
        case_property_ids = {
            property_id
            for state_case_spec in state_spec.cases
            for property_id in state_case_spec.property_ids
        }
        properties = {
            identity: item
            for identity, item in properties.items()
            if not (
                _state_target_scope_identity(
                    item.interface_id,
                    item.component_path,
                )
                == scope
                and item.property_id in case_property_ids
            )
        }
    for assignment in command.assignments:
        interface_spec = interfaces.get(assignment.interface_id)
        component_spec = (
            _resolve_component(interface_spec, assignment.component_path)
            if interface_spec is not None
            else None
        )
        property_spec = (
            next(
                (
                    item
                    for item in component_spec.properties
                    if item.id == assignment.property_id
                ),
                None,
            )
            if component_spec is not None
            else None
        )
        if property_spec is not None and property_spec.access == "write_only":
            continue
        properties[
            _property_target_identity(
                assignment.interface_id,
                assignment.component_path,
                assignment.property_id,
            )
        ] = _InstrumentPropertyState(
            interface_id=assignment.interface_id,
            component_path=list(assignment.component_path),
            property_id=assignment.property_id,
            value=assignment.value,
        )
    return _ProjectedInstrumentState(
        instrument_id=state.instrument_id,
        properties=tuple(
            properties[key] for key in sorted(properties, key=_property_target_sort_key)
        ),
    )


def _state_properties_by_scope(
    state: _InstrumentStateSnapshot | _ProjectedInstrumentState,
) -> dict[_StateTargetScopeIdentity, list[_InstrumentPropertyState]]:
    grouped: dict[_StateTargetScopeIdentity, list[_InstrumentPropertyState]] = {}
    for property_state in state.properties:
        scope = _state_target_scope_identity(
            property_state.interface_id,
            property_state.component_path,
        )
        grouped.setdefault(scope, []).append(property_state)
    return grouped


def _static_observable_state_scopes(
    description: InstrumentDescription,
) -> Iterable[tuple[_StateTargetScopeIdentity, InterfaceSpec | ComponentSpec]]:
    def walk(
        interface_id: str,
        component_path: tuple[str, ...],
        component_spec: InterfaceSpec | ComponentSpec,
    ) -> Iterable[tuple[_StateTargetScopeIdentity, InterfaceSpec | ComponentSpec]]:
        if any(
            property_spec.access != "write_only"
            for property_spec in component_spec.properties
        ):
            yield (
                _state_target_scope_identity(interface_id, component_path),
                component_spec,
            )
        for child in component_spec.components:
            yield from walk(
                interface_id,
                (*component_path, child.id),
                child,
            )

    for interface_spec in description.interfaces:
        yield from walk(interface_spec.id, (), interface_spec)


def _state_case_by_property(
    state: DiscriminatedStateSpec,
) -> dict[str, str]:
    return {
        property_id: state_case_spec.value
        for state_case_spec in state.cases
        for property_id in state_case_spec.property_ids
    }


def _validate_state_case_assignments(
    assignments: Sequence[InstrumentStateAssignment],
    component_spec: InterfaceSpec | ComponentSpec,
    *,
    baseline_properties: Sequence[_InstrumentPropertyState] | None,
    require_explicit_state_case: bool,
) -> list[Problem]:
    state = component_spec.state
    if state is None:
        return []
    by_property = {assignment.property_id: assignment for assignment in assignments}
    case_by_property = _state_case_by_property(state)
    referenced_cases = {
        case_by_property[assignment.property_id]
        for assignment in assignments
        if assignment.property_id in case_by_property
    }
    if len(referenced_cases) > 1:
        return [
            _problem(
                "instrument_driver_mixed_state_cases",
                "one state target cannot mix properties from multiple cases",
                "assignments",
            )
        ]
    explicit = by_property.get(state.discriminator_property_id)
    explicit_case = (
        explicit.value.root
        if explicit is not None and isinstance(explicit.value.root, str)
        else None
    )
    discriminator = next(
        (
            property_state
            for property_state in baseline_properties or ()
            if property_state.property_id == state.discriminator_property_id
        ),
        None,
    )
    baseline_case = (
        discriminator.value.root
        if discriminator is not None and isinstance(discriminator.value.root, str)
        else None
    )
    if explicit_case is not None:
        if referenced_cases and explicit_case not in referenced_cases:
            return [
                _problem(
                    "instrument_driver_state_case_mismatch",
                    f"state case {explicit_case!r} does not accept "
                    f"{next(iter(referenced_cases))!r} case properties",
                    "assignments",
                )
            ]
        if baseline_case != explicit_case:
            return _incomplete_state_case_problems(
                explicit_case,
                by_property=by_property,
                component_spec=component_spec,
            )
        return []
    if not referenced_cases:
        return []
    if baseline_properties is None:
        if not require_explicit_state_case:
            return _incomplete_state_case_problems(
                next(iter(referenced_cases)),
                by_property=by_property,
                component_spec=component_spec,
            )
        return [
            _problem(
                "instrument_driver_state_case_unknown",
                "case-specific state requires an explicit discriminator",
                "assignments",
                state.discriminator_property_id,
            )
        ]
    referenced_case = next(iter(referenced_cases))
    if baseline_case is None:
        return [
            _problem(
                "instrument_driver_state_case_unknown",
                "case-specific state requires an observed discriminator value",
                "baseline",
                state.discriminator_property_id,
            )
        ]
    if baseline_case != referenced_case:
        return [
            _problem(
                "instrument_driver_state_case_mismatch",
                f"observed state case {baseline_case!r} does not accept "
                f"{referenced_case!r} case properties; set "
                f"{state.discriminator_property_id} explicitly to switch cases",
                "assignments",
            )
        ]
    return []


def _incomplete_state_case_problems(
    case_value: str,
    *,
    by_property: Mapping[str, InstrumentStateAssignment],
    component_spec: InterfaceSpec | ComponentSpec,
) -> list[Problem]:
    state = component_spec.state
    if state is None:
        return []
    selected_case = next(
        (state_case for state_case in state.cases if state_case.value == case_value),
        None,
    )
    if selected_case is None:
        return []
    property_specs = {
        property_spec.id: property_spec for property_spec in component_spec.properties
    }
    missing = [
        property_id
        for property_id in selected_case.property_ids
        if property_specs[property_id].access != "read_only"
        and property_id not in by_property
    ]
    if not missing:
        return []
    return [
        _problem(
            "instrument_driver_state_case_incomplete",
            f"state case {case_value!r} requires all writable case properties "
            f"without a matching baseline; missing {missing!r}",
            "assignments",
        )
    ]


def _validate_snapshot_scope(
    properties: Sequence[_InstrumentPropertyState],
    component_spec: InterfaceSpec | ComponentSpec,
    *,
    scope: _StateTargetScopeIdentity,
) -> list[Problem]:
    by_property = {
        property_state.property_id: property_state for property_state in properties
    }
    property_specs = {
        property_spec.id: property_spec for property_spec in component_spec.properties
    }
    state = component_spec.state
    if state is None:
        required = {
            property_id
            for property_id, property_spec in property_specs.items()
            if property_spec.access != "write_only"
        }
        return _snapshot_missing_properties(scope, required - set(by_property))
    universal = {
        state.discriminator_property_id,
        *state.common_property_ids,
    }
    required = {
        property_id
        for property_id in universal
        if property_specs[property_id].access != "write_only"
    }
    discriminator = by_property.get(state.discriminator_property_id)
    active_case = discriminator.value.root if discriminator is not None else None
    if isinstance(active_case, str):
        selected_case = next(
            (case for case in state.cases if case.value == active_case),
            None,
        )
        if selected_case is not None:
            required.update(
                property_id
                for property_id in selected_case.property_ids
                if property_specs[property_id].access != "write_only"
            )
    problems = _snapshot_missing_properties(scope, required - set(by_property))
    if not isinstance(active_case, str):
        return problems
    case_by_property = _state_case_by_property(state)
    inactive = sorted(
        property_id
        for property_id in by_property
        if property_id in case_by_property
        and case_by_property[property_id] != active_case
    )
    if not inactive:
        return problems
    problems.append(
        _snapshot_problem(
            "instrument_driver_snapshot_inactive_state_property",
            f"state case {active_case!r} cannot contain properties {inactive!r}",
            "properties",
        )
    )
    return problems


def _snapshot_missing_properties(
    scope: _StateTargetScopeIdentity,
    missing: set[str],
) -> list[Problem]:
    if not missing:
        return []
    interface_id, component_path = scope
    component = "/".join(component_path) or "<root>"
    selected = sorted(missing)
    return [
        _snapshot_problem(
            "instrument_driver_snapshot_missing_properties",
            f"observed {interface_id} {component} state is missing "
            f"properties {selected!r}",
            "properties",
        )
    ]


def _validate_state_value(
    *,
    property_id: str,
    value: StateValue,
    spec: PropertySpec,
) -> list[Problem]:
    try:
        validate_literal(spec.value_type, value.root, path=("value",))
    except ValueValidationError as error:
        return _property_value_mismatch(
            property_id,
            error.reason,
            path=error.path,
        )
    return []


def _validate_operation_argument(
    *,
    argument_id: str,
    value: StateValue,
    spec: OperationArgumentSpec,
    payload_schemas: Mapping[str, str],
) -> list[Problem]:
    atom = spec.value_type.atom
    literal = value.root
    if isinstance(atom, PayloadType):
        if not isinstance(literal, PayloadRef):
            return _operation_argument_value_mismatch(
                argument_id,
                f"expected payload reference, got {literal!r}",
            )
        schema_id = payload_schemas.get(literal.payload_id)
        if schema_id is None:
            return [
                _problem(
                    "instrument_driver_unknown_payload",
                    f"{argument_id} references unknown payload {literal.payload_id}",
                    "arguments",
                    argument_id,
                    "value",
                    "payload_id",
                )
            ]
        if schema_id != atom.schema_id:
            return _operation_argument_value_mismatch(
                argument_id,
                f"expected payload {atom.schema_id!r}, got {schema_id!r}",
                path=("value", "payload_id"),
            )
        return []
    try:
        validate_literal(spec.value_type, literal, path=("value",))
    except ValueValidationError as error:
        return _operation_argument_value_mismatch(
            argument_id,
            error.reason,
            path=error.path,
        )
    return []


def _operation_argument_value_mismatch(
    argument_id: str,
    reason: str,
    *,
    path: ValuePath = ("value",),
) -> list[Problem]:
    return [
        _problem(
            "instrument_driver_operation_argument_value_mismatch",
            f"{argument_id}: {reason}",
            "arguments",
            argument_id,
            *path,
        )
    ]


def _property_value_mismatch(
    property_id: str,
    reason: str,
    *,
    path: ValuePath = ("value",),
) -> list[Problem]:
    return [
        _problem(
            "instrument_driver_property_value_mismatch",
            f"{property_id}: {reason}",
            *path,
        )
    ]


def _validate_instrument_scalar(
    value: Scalar,
    *,
    allow_payload: bool,
) -> Scalar:
    if not isinstance(
        value.atom,
        BoolType | IntType | FloatType | StringType | QuantityType | PayloadType,
    ):
        raise ValueError(
            "instrument values support bool, int, float, string, quantity, and payload"
        )
    if isinstance(value.atom, PayloadType) and not allow_payload:
        raise ValueError("instrument properties cannot contain payload values")
    if isinstance(value.atom, FloatType | QuantityType) and not value.atom.finite:
        raise ValueError("instrument numeric values must require finite values")
    return value


def _require_unique(values: Iterable[str], label: str) -> None:
    selected = tuple(values)
    if len(selected) != len(set(selected)):
        raise ValueError(f"{label} must be unique")


def validate_instrument_description_collection(
    instruments: Sequence[InstrumentDescription],
) -> None:
    """Require stable identities across one advertised instrument collection."""

    instrument_ids = [instrument.instrument_id for instrument in instruments]
    duplicates = sorted(
        instrument_id
        for instrument_id in set(instrument_ids)
        if instrument_ids.count(instrument_id) > 1
    )
    if duplicates:
        raise ValueError(
            "instrument descriptions require unique instrument ids: "
            f"{', '.join(duplicates)}"
        )
    declared: dict[str, InterfaceSpec] = {}
    for instrument in instruments:
        for interface_spec in instrument.interfaces:
            previous = declared.setdefault(interface_spec.id, interface_spec)
            if previous != interface_spec:
                raise ValueError(
                    f"interface {interface_spec.id!r} must have one stable "
                    "specification within an instrument catalog"
                )


def _validate_acquisition_state_references(
    description: InstrumentDescription,
) -> None:
    interfaces = {interface.id: interface for interface in description.interfaces}
    for interface_spec in description.interfaces:
        for component_spec in _component_specs(interface_spec):
            for acquisition_spec in component_spec.acquisitions:
                if not isinstance(
                    acquisition_spec,
                    StateDiscriminatedAcquisitionSpec,
                ):
                    continue
                reference = acquisition_spec.discriminator
                target_interface = interfaces.get(reference.interface_id)
                target_component = (
                    _resolve_component(target_interface, reference.component_path)
                    if target_interface is not None
                    else None
                )
                target_state = (
                    target_component.state if target_component is not None else None
                )
                if (
                    target_state is None
                    or target_state.discriminator_property_id != reference.property_id
                ):
                    raise ValueError(
                        f"acquisition {acquisition_spec.id!r} discriminator must "
                        "reference a declared discriminated state"
                    )
                acquisition_cases = tuple(case.value for case in acquisition_spec.cases)
                state_cases = tuple(case.value for case in target_state.cases)
                if acquisition_cases != state_cases:
                    raise ValueError(
                        f"acquisition {acquisition_spec.id!r} case values must "
                        "exactly match its discriminator state cases"
                    )


def _component_specs(
    spec: InterfaceSpec | ComponentSpec,
) -> Iterable[InterfaceSpec | ComponentSpec]:
    yield spec
    for child in spec.components:
        yield from _component_specs(child)


def _validate_component_members(
    spec: InterfaceSpec | ComponentSpec,
) -> None:
    _require_unique((item.id for item in spec.properties), "property ids")
    _require_unique((item.id for item in spec.operations), "operation ids")
    _require_unique((item.id for item in spec.acquisitions), "acquisition ids")
    _require_unique((item.id for item in spec.components), "component ids")
    state = spec.state
    if state is None:
        return
    properties = {item.id: item for item in spec.properties}
    discriminator = properties.get(state.discriminator_property_id)
    if discriminator is None:
        raise ValueError("state discriminator must reference a declared property")
    if discriminator.access == "write_only":
        raise ValueError("state discriminator must be observable")
    atom = discriminator.value_type.atom
    case_values = tuple(case.value for case in state.cases)
    if not isinstance(atom, StringType) or atom.choices != case_values:
        raise ValueError(
            "state discriminator must be a string property whose choices "
            "exactly match case values"
        )
    partition = {
        state.discriminator_property_id,
        *state.common_property_ids,
        *(property_id for case in state.cases for property_id in case.property_ids),
    }
    declared = set(properties)
    if partition != declared:
        missing = sorted(declared - partition)
        unknown = sorted(partition - declared)
        issues: list[str] = []
        if missing:
            issues.append(f"unclassified properties: {missing!r}")
        if unknown:
            issues.append(f"unknown properties: {unknown!r}")
        raise ValueError("state property partition is incomplete: " + "; ".join(issues))


def _resolve_component(
    interface_spec: InterfaceSpec,
    component_path: Sequence[str],
) -> InterfaceSpec | ComponentSpec | None:
    selected: InterfaceSpec | ComponentSpec = interface_spec
    for component_id in component_path:
        match = next(
            (
                component
                for component in selected.components
                if component.id == component_id
            ),
            None,
        )
        if match is None:
            return None
        selected = match
    return selected


def _problem(code: str, message: str, *path: LocationPathItem) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument_state_command", *path),
    )


def _snapshot_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument_state_snapshot", *path),
    )
