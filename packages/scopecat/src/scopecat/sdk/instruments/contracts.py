"""Instrument driver SDK."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.value_type_wire import CapabilityScalarWire
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
from scopecat.measurements.results import MeasurementDType
from scopecat.records._metadata import JsonMetadata
from scopecat.records.artifact import CommandPayload
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.instrument import (
    CommandChannelBinding as _CommandChannelBinding,
)
from scopecat.records.instrument import (
    InstrumentReadback as _InstrumentReadback,
)
from scopecat.records.instrument import (
    InstrumentStateField as _InstrumentStateField,
)
from scopecat.records.instrument import (
    InstrumentStateSnapshot as _InstrumentStateSnapshot,
)
from scopecat.records.instrument import (
    state_target_identity as _state_target_identity,
)
from scopecat.records.instrument import (
    state_target_sort_key as _state_target_sort_key,
)
from scopecat.records.instrument import (
    validate_entity_target as _validate_entity_target,
)
from scopecat.sdk.problems import (
    LocationPathItem,
    Problem,
    ProblemPhase,
    model_location,
    problem,
)

type _NonEmptyId = Annotated[str, Field(min_length=1)]


class CapabilityField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    value_type: CapabilityScalarWire

    @field_validator("value_type")
    @classmethod
    def validate_value_type(cls, value: Scalar) -> Scalar:
        if not isinstance(
            value.atom,
            BoolType | IntType | FloatType | StringType | QuantityType | PayloadType,
        ):
            msg = (
                "instrument capability fields support bool, int, float, string, "
                "quantity, and payload"
            )
            raise ValueError(msg)
        if isinstance(value.atom, FloatType | QuantityType) and not value.atom.finite:
            msg = "instrument capability numeric fields must require finite values"
            raise ValueError(msg)
        return value


class ProductAxisDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int | None = None
    unit: str | None = None


class ProductDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    dtype: MeasurementDType = "float64"
    unit: str | None = None
    axes: list[ProductAxisDescription] = Field(default_factory=list)


class CapabilityDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    fields: list[CapabilityField] = Field(default_factory=list)
    products: list[ProductDescription] = Field(default_factory=list)


class InstrumentDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    implementation_id: str
    implementation_version: str
    capabilities: list[CapabilityDescription] = Field(default_factory=list)


class InstrumentStateCommandField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    capability_id: str
    field_path: str
    value: StateValue
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[_CommandChannelBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> InstrumentStateCommandField:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


class InstrumentStateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str | None = None
    instrument_id: str
    fields: list[InstrumentStateCommandField] = Field(default_factory=list)
    payloads: dict[str, CommandPayload] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> InstrumentStateCommand:
        identities = [
            _state_target_identity(
                field.capability_id,
                field.field_path,
                field.entity_ids,
                field.channel_bindings,
            )
            for field in self.fields
        ]
        if len(identities) != len(set(identities)):
            msg = "instrument state command field targets must be unique"
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

    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)


class CollectProductRequest(BaseModel):
    """One explicitly capability-scoped provider product request.

    Capability identity is required because a provider must not infer ownership
    from a product key or from accidental global uniqueness. Planning derives
    it from the same logical resource contract used for physical binding.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    capability_id: _NonEmptyId
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    dimensions: list[CollectAxisRequest] = Field(default_factory=list)
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[_CommandChannelBinding] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_target(self) -> CollectProductRequest:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


class CollectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str | None = None
    instrument_id: str
    point_index: int
    point_count: int
    requests: list[CollectProductRequest] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_requests(self) -> CollectCommand:
        request_ids = [request.id for request in self.requests]
        if len(request_ids) != len(set(request_ids)):
            msg = "collect command request ids must be unique"
            raise ValueError(msg)
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

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt: ...

    def collect(self, command: CollectCommand) -> CollectReceipt: ...

    def cleanup(self) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True)
class InstrumentProviderContext:
    config: ConfigProfileSnapshot


@dataclass(frozen=True)
class InstrumentProviderResult:
    drivers: tuple[InstrumentDriver, ...]
    problems: tuple[Problem, ...] = ()
    metadata: dict[str, JsonValue] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class InstrumentProviderDescription:
    """Pure, config-specific declaration of instruments a provider can create."""

    provider_id: str
    instruments: tuple[InstrumentDescription, ...] = ()
    problems: tuple[Problem, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id:
            msg = "instrument provider id must be non-empty"
            raise ValueError(msg)
        instrument_ids = [instrument.instrument_id for instrument in self.instruments]
        if len(instrument_ids) != len(set(instrument_ids)):
            duplicates = sorted(
                instrument_id
                for instrument_id in set(instrument_ids)
                if instrument_ids.count(instrument_id) > 1
            )
            msg = (
                "instrument provider descriptions require unique instrument ids: "
                f"{', '.join(duplicates)}"
            )
            raise ValueError(msg)


class InstrumentProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription: ...

    def provide(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderResult: ...


def capability(
    id: str,
    *,
    fields: list[CapabilityField] | tuple[CapabilityField, ...] = (),
    products: list[ProductDescription] | tuple[ProductDescription, ...] = (),
) -> CapabilityDescription:
    return CapabilityDescription(
        id=id,
        fields=list(fields),
        products=list(products),
    )


def product_axis(
    id: str,
    *,
    size: int | None = None,
    kind: str | None = None,
    unit: str | None = None,
) -> ProductAxisDescription:
    return ProductAxisDescription(
        id=id,
        kind=kind or id,
        size=size,
        unit=unit,
    )


def product(
    key: str,
    *,
    dtype: MeasurementDType = "float64",
    unit: str | None = None,
    axes: list[ProductAxisDescription] | tuple[ProductAxisDescription, ...] = (),
) -> ProductDescription:
    return ProductDescription(
        key=key,
        dtype=dtype,
        unit=unit,
        axes=list(axes),
    )


def quantity_field(
    id: str,
    *,
    unit: str,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(QuantityType(unit=unit)),
    )


def bool_field(
    id: str,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(BoolType()),
    )


def int_field(
    id: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(IntType(minimum=minimum, maximum=maximum)),
    )


def float_field(
    id: str,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(FloatType()),
    )


def string_field(
    id: str,
    *,
    choices: tuple[str, ...] | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(StringType(choices=choices)),
    )


def enum_field(
    id: str,
    *,
    choices: tuple[str, ...],
) -> CapabilityField:
    return string_field(id, choices=choices)


def payload_field(
    id: str,
    *,
    schema_id: str,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(PayloadType(schema_id=schema_id)),
    )


def validate_state_command(
    *,
    command: InstrumentStateCommand,
    description: InstrumentDescription,
    payloads: dict[str, CommandPayload] | None = None,
) -> list[Problem]:
    problems: list[Problem] = []
    available_payloads = {**command.payloads, **(payloads or {})}
    if command.instrument_id != description.instrument_id:
        problems.append(
            _problem(
                "instrument_driver_mismatch",
                f"{description.instrument_id} cannot apply command for "
                f"{command.instrument_id}",
                "instrument_id",
            )
        )
        return problems
    capability_fields = {
        capability.id: {field.id: field for field in capability.fields}
        for capability in description.capabilities
    }
    for field in command.fields:
        if field.resource_id != command.instrument_id:
            problems.append(
                _problem(
                    "instrument_driver_resource_mismatch",
                    f"{command.instrument_id} cannot control {field.resource_id}",
                    "resource_id",
                )
            )
            continue
        field_specs = capability_fields.get(field.capability_id)
        if field_specs is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_capability",
                    f"{command.instrument_id} does not support {field.capability_id}",
                    "capability_id",
                )
            )
            continue
        field_spec = field_specs.get(field.field_path)
        if field_spec is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_field",
                    f"{command.instrument_id} does not support {field.field_path}",
                    "field_path",
                )
            )
            continue
        problems.extend(
            _validate_state_value(
                field_path=field.field_path,
                value=field.value,
                spec=field_spec,
                payloads=available_payloads,
            )
        )
    return problems


def apply_state_command_to_snapshot(
    snapshot: _InstrumentStateSnapshot,
    command: InstrumentStateCommand,
) -> _InstrumentStateSnapshot:
    fields = {
        _state_target_identity(
            field.capability_id,
            field.field_path,
            field.entity_ids,
            field.channel_bindings,
        ): field.model_copy(deep=True)
        for field in snapshot.fields
    }
    for field in command.fields:
        fields[
            _state_target_identity(
                field.capability_id,
                field.field_path,
                field.entity_ids,
                field.channel_bindings,
            )
        ] = _InstrumentStateField(
            capability_id=field.capability_id,
            field_path=field.field_path,
            value=field.value,
            entity_ids=list(field.entity_ids),
            channel_bindings=[
                binding.model_copy(deep=True) for binding in field.channel_bindings
            ],
        )
    return _InstrumentStateSnapshot(
        instrument_id=snapshot.instrument_id,
        fields=[fields[key] for key in sorted(fields, key=_state_target_sort_key)],
        metadata=dict(snapshot.metadata),
    )


def _validate_state_value(
    *,
    field_path: str,
    value: StateValue,
    spec: CapabilityField,
    payloads: dict[str, CommandPayload],
) -> list[Problem]:
    atom = spec.value_type.atom
    state_literal = value.root
    literal: object = state_literal
    literal_path: ValuePath = ("value",)
    if isinstance(atom, PayloadType):
        if not isinstance(state_literal, PayloadRef):
            return _field_value_mismatch(
                field_path,
                f"expected payload reference, got {state_literal!r}",
            )
        payload = payloads.get(state_literal.payload_id)
        if payload is None:
            return [
                _problem(
                    "instrument_driver_unknown_payload",
                    f"{field_path} references unknown payload "
                    f"{state_literal.payload_id}",
                    "value",
                    "payload_id",
                )
            ]
        literal = PayloadValue(schema_id=payload.schema_id, payload=payload.payload)
        literal_path = ("value", "payload_id")
    try:
        validate_literal(spec.value_type, literal, path=literal_path)
    except ValueValidationError as error:
        return _field_value_mismatch(
            field_path,
            error.reason,
            path=error.path,
        )
    return []


def _field_value_mismatch(
    field_path: str,
    reason: str,
    *,
    path: ValuePath = ("value",),
) -> list[Problem]:
    return [
        _problem(
            "instrument_driver_field_value_mismatch",
            f"{field_path}: {reason}",
            *path,
        )
    ]


def _problem(code: str, message: str, *path: LocationPathItem) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument_state_command", *path),
    )
