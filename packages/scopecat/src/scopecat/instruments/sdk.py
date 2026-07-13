"""Instrument driver SDK."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from scopecat._value_type_wire import ScalarWire, scalar_type_wire_schema
from scopecat.models.artifact import CommandPayload
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity as QuantityValue
from scopecat.models.provider import ProviderOptionDescription
from scopecat.models.state import PayloadRef, StateLiteral, StateValue
from scopecat.models.value import PayloadValue
from scopecat.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.results import MeasurementDType, MeasurementValue
from scopecat.value_types import Bool as BoolType
from scopecat.value_types import Float as FloatType
from scopecat.value_types import Int as IntType
from scopecat.value_types import Payload as PayloadType
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar
from scopecat.value_types import String as StringType
from scopecat.value_validation import ValuePath, ValueValidationError, validate_literal

type _NonEmptyId = Annotated[str, Field(min_length=1)]

_CAPABILITY_FIELD_SCALAR_WIRE_SCHEMA = scalar_type_wire_schema(
    ("bool", "int", "float", "string", "quantity", "payload"),
    finite_only=True,
    allow_nullable=False,
)

type CapabilityFieldScalar = Annotated[
    ScalarWire,
    WithJsonSchema(_CAPABILITY_FIELD_SCALAR_WIRE_SCHEMA, mode="validation"),
    WithJsonSchema(_CAPABILITY_FIELD_SCALAR_WIRE_SCHEMA, mode="serialization"),
]


class CapabilityField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    value_type: CapabilityFieldScalar
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={
            "propertyNames": {"not": {"const": "payload_kinds"}},
        },
    )

    @field_validator("value_type")
    @classmethod
    def validate_value_type(cls, value: Scalar) -> Scalar:
        if value.nullable:
            msg = "instrument capability fields must be non-nullable"
            raise ValueError(msg)
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

    @field_validator("metadata")
    @classmethod
    def reject_legacy_payload_kinds(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "payload_kinds" in value:
            msg = (
                "payload_kinds is no longer metadata; declare Payload.schema_id "
                "in value_type"
            )
            raise ValueError(msg)
        return value


class ProductAxisDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int | None = None
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    kind: Literal["observable", "artifact", "readback", "expression"] = "observable"
    dtype: MeasurementDType = "float64"
    unit: str | None = None
    axes: list[ProductAxisDescription] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    fields: list[CapabilityField] = Field(default_factory=list)
    products: list[ProductDescription] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.instrument_description.v1"] = (
        "scopecat.instrument_description.v1"
    )
    instrument_id: str
    implementation_id: str
    implementation_version: str
    capabilities: list[CapabilityDescription] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommandChannelBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: _NonEmptyId
    channel_id: _NonEmptyId
    line_id: _NonEmptyId | None = None
    capability: _NonEmptyId | None = None
    group_ids: list[_NonEmptyId] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _validate_entity_target(
    entity_ids: list[str],
    channel_bindings: list[CommandChannelBinding],
) -> None:
    if any(not entity_id for entity_id in entity_ids):
        msg = "entity target ids must be non-empty"
        raise ValueError(msg)
    if len(entity_ids) != len(set(entity_ids)):
        msg = "entity target ids must be unique"
        raise ValueError(msg)
    unbound = sorted(
        {
            binding.entity_id
            for binding in channel_bindings
            if binding.entity_id not in entity_ids
        }
    )
    if unbound:
        msg = "channel bindings reference entities outside the target: " + ", ".join(
            unbound
        )
        raise ValueError(msg)


class InstrumentStateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    field_path: str
    value: StateValue
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[CommandChannelBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> InstrumentStateField:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


class InstrumentStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.instrument_state_snapshot.v2"] = (
        "scopecat.instrument_state_snapshot.v2"
    )
    instrument_id: str
    fields: list[InstrumentStateField] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> InstrumentStateSnapshot:
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
            msg = "instrument state snapshot field targets must be unique"
            raise ValueError(msg)
        return self


class InstrumentStateCommandField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    capability_id: str
    field_path: str
    value: StateValue
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[CommandChannelBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> InstrumentStateCommandField:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


class InstrumentStateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.instrument_state_command.v3"] = (
        "scopecat.instrument_state_command.v3"
    )
    operation_id: str | None = None
    attempt: int = Field(default=1, ge=1)
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

    schema_version: Literal["scopecat.apply_receipt.v3"] = "scopecat.apply_receipt.v3"
    status: Literal["applied", "not_applied", "unknown"] = "applied"
    problems: tuple[Problem, ...] = ()
    state: InstrumentStateSnapshot | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> ApplyReceipt:
        blocking = has_blocking_problems(self.problems)
        if self.status == "applied" and blocking:
            msg = "an applied receipt cannot contain blocking problems"
            raise ValueError(msg)
        if self.status != "applied" and not blocking:
            msg = "a negative or unknown apply receipt requires a blocking problem"
            raise ValueError(msg)
        return self


class InstrumentActionCommandField(BaseModel):
    """One typed argument supplied to a one-shot instrument action."""

    model_config = ConfigDict(extra="forbid")

    field_path: _NonEmptyId
    value: StateValue
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[CommandChannelBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> InstrumentActionCommandField:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


class InstrumentActionCommand(BaseModel):
    """A one-shot effect command that is never state-diffed or deduplicated."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.instrument_action_command.v1"] = (
        "scopecat.instrument_action_command.v1"
    )
    operation_id: _NonEmptyId
    attempt: int = Field(default=1, ge=1)
    instrument_id: _NonEmptyId
    capability_id: _NonEmptyId
    fields: list[InstrumentActionCommandField] = Field(default_factory=list)
    payloads: dict[str, CommandPayload] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_fields(self) -> InstrumentActionCommand:
        identities = [
            _state_target_identity(
                self.capability_id,
                field.field_path,
                field.entity_ids,
                field.channel_bindings,
            )
            for field in self.fields
        ]
        if len(identities) != len(set(identities)):
            msg = "instrument action command field targets must be unique"
            raise ValueError(msg)
        return self


class ActionReceipt(BaseModel):
    """Explicit outcome of a one-shot action attempt.

    ``not_performed`` proves the action had no effect and is therefore safe for
    a caller to retry deliberately. ``unknown`` means it may have happened and
    must never be retried automatically.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.action_receipt.v1"] = "scopecat.action_receipt.v1"
    status: Literal["performed", "not_performed", "unknown"] = "performed"
    problems: tuple[Problem, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> ActionReceipt:
        blocking = has_blocking_problems(self.problems)
        if self.status == "performed" and blocking:
            msg = "a performed action receipt cannot contain blocking problems"
            raise ValueError(msg)
        if self.status != "performed" and not blocking:
            msg = "a negative or unknown action receipt requires a blocking problem"
            raise ValueError(msg)
        return self


class CollectAxisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    capability_id: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    dimensions: list[CollectAxisRequest] = Field(default_factory=list)
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[CommandChannelBinding] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_target(self) -> CollectProductRequest:
        _validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


class CollectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.collect_command.v1"] = (
        "scopecat.collect_command.v1"
    )
    operation_id: str | None = None
    attempt: int = Field(default=1, ge=1)
    instrument_id: str
    point_index: int
    point_count: int
    requests: list[CollectProductRequest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_requests(self) -> CollectCommand:
        request_ids = [request.id for request in self.requests]
        if len(request_ids) != len(set(request_ids)):
            msg = "collect command request ids must be unique"
            raise ValueError(msg)
        return self


class InstrumentReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, MeasurementValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CollectReceipt(BaseModel):
    """Explicit outcome reported after one collection command."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.collect_receipt.v1"] = (
        "scopecat.collect_receipt.v1"
    )
    status: Literal["collected", "not_collected", "unknown"] = "collected"
    problems: tuple[Problem, ...] = ()
    readback: InstrumentReadback | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_readback_outcome(self) -> CollectReceipt:
        if self.status == "collected" and self.readback is None:
            msg = "a collected receipt requires a readback"
            raise ValueError(msg)
        if self.status == "not_collected" and self.readback is not None:
            msg = "a not_collected receipt must not contain a readback"
            raise ValueError(msg)
        blocking = has_blocking_problems(self.problems)
        if self.status == "collected" and blocking:
            msg = "a collected receipt cannot contain blocking problems"
            raise ValueError(msg)
        if self.status != "collected" and not blocking:
            msg = "a negative or unknown collect receipt requires a blocking problem"
            raise ValueError(msg)
        return self


@dataclass
class DriverFault(Exception):
    """Exceptional driver control flow carrying one stable public problem."""

    problem: Problem

    def __post_init__(self) -> None:
        if not has_blocking_problems((self.problem,)):
            msg = "driver fault requires a blocking problem"
            raise ValueError(msg)
        Exception.__init__(self, self.problem.message)


class InstrumentDriver(Protocol):
    instrument_id: str
    implementation_id: str
    implementation_version: str

    def describe(self) -> InstrumentDescription: ...

    def read_state(self) -> InstrumentStateSnapshot: ...

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt: ...

    def action(self, command: InstrumentActionCommand) -> ActionReceipt: ...

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
    label: str | None = None
    description: str | None = None
    options: tuple[ProviderOptionDescription, ...] = ()
    metadata: dict[str, Any] = dc_field(default_factory=dict)

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
    id: str,  # noqa: A002
    *,
    fields: list[CapabilityField] | tuple[CapabilityField, ...] = (),
    products: list[ProductDescription] | tuple[ProductDescription, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> CapabilityDescription:
    return CapabilityDescription(
        id=id,
        fields=list(fields),
        products=list(products),
        metadata=dict(metadata or {}),
    )


def product_axis(
    id: str,  # noqa: A002
    *,
    size: int | None = None,
    kind: str | None = None,
    unit: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProductAxisDescription:
    return ProductAxisDescription(
        id=id,
        kind=kind or id,
        size=size,
        unit=unit,
        metadata=dict(metadata or {}),
    )


def product(
    key: str,
    *,
    kind: Literal["observable", "artifact", "readback", "expression"] = "observable",
    dtype: MeasurementDType = "float64",
    unit: str | None = None,
    axes: list[ProductAxisDescription] | tuple[ProductAxisDescription, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> ProductDescription:
    return ProductDescription(
        key=key,
        kind=kind,
        dtype=dtype,
        unit=unit,
        axes=list(axes),
        metadata=dict(metadata or {}),
    )


def quantity_field(
    id: str,  # noqa: A002
    *,
    unit: str,
    metadata: dict[str, Any] | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(QuantityType(unit=unit)),
        metadata=dict(metadata or {}),
    )


def bool_field(
    id: str,  # noqa: A002
    *,
    metadata: dict[str, Any] | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(BoolType()),
        metadata=dict(metadata or {}),
    )


def int_field(
    id: str,  # noqa: A002
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(IntType(minimum=minimum, maximum=maximum)),
        metadata=dict(metadata or {}),
    )


def float_field(
    id: str,  # noqa: A002
    *,
    metadata: dict[str, Any] | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(FloatType()),
        metadata=dict(metadata or {}),
    )


def string_field(
    id: str,  # noqa: A002
    *,
    min_length: int = 0,
    max_length: int | None = None,
    pattern: str | None = None,
    choices: tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(
            StringType(
                min_length=min_length,
                max_length=max_length,
                pattern=pattern,
                choices=choices,
            )
        ),
        metadata=dict(metadata or {}),
    )


def enum_field(
    id: str,  # noqa: A002
    *,
    choices: tuple[str, ...],
    metadata: dict[str, Any] | None = None,
) -> CapabilityField:
    return string_field(id, choices=choices, metadata=metadata)


def payload_field(
    id: str,  # noqa: A002
    *,
    schema_id: str,
    metadata: dict[str, Any] | None = None,
) -> CapabilityField:
    return CapabilityField(
        id=id,
        value_type=Scalar(PayloadType(schema_id=schema_id)),
        metadata=dict(metadata or {}),
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


def validate_action_command(
    *,
    command: InstrumentActionCommand,
    description: InstrumentDescription,
    payloads: dict[str, CommandPayload] | None = None,
) -> list[Problem]:
    """Validate an action against the same typed capability field contract."""

    if command.instrument_id != description.instrument_id:
        return [
            _problem(
                "instrument_driver_mismatch",
                f"{description.instrument_id} cannot perform action for "
                f"{command.instrument_id}",
                "instrument_id",
            )
        ]
    capability = next(
        (
            candidate
            for candidate in description.capabilities
            if candidate.id == command.capability_id
        ),
        None,
    )
    if capability is None:
        return [
            _problem(
                "instrument_driver_unsupported_capability",
                f"{command.instrument_id} does not support {command.capability_id}",
                "capability_id",
            )
        ]
    specs = {field.id: field for field in capability.fields}
    available_payloads = {**command.payloads, **(payloads or {})}
    problems: list[Problem] = []
    for field in command.fields:
        spec = specs.get(field.field_path)
        if spec is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_field",
                    f"{command.instrument_id} does not support {field.field_path}",
                    "fields",
                    field.field_path,
                )
            )
            continue
        problems.extend(
            _validate_state_value(
                field_path=field.field_path,
                value=field.value,
                spec=spec,
                payloads=available_payloads,
            )
        )
    return problems


def apply_state_command_to_snapshot(
    snapshot: InstrumentStateSnapshot,
    command: InstrumentStateCommand,
) -> InstrumentStateSnapshot:
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
        ] = InstrumentStateField(
            capability_id=field.capability_id,
            field_path=field.field_path,
            value=field.value.model_copy(deep=True),
            entity_ids=list(field.entity_ids),
            channel_bindings=[
                binding.model_copy(deep=True) for binding in field.channel_bindings
            ],
        )
    return InstrumentStateSnapshot(
        instrument_id=snapshot.instrument_id,
        fields=[fields[key] for key in sorted(fields, key=_state_target_sort_key)],
        metadata=dict(snapshot.metadata),
    )


type _StateTargetIdentity = tuple[
    str,
    str,
    tuple[str, ...],
    tuple[tuple[str, str, str | None, str | None, tuple[str, ...]], ...],
]


def _state_target_identity(
    capability_id: str,
    field_path: str,
    entity_ids: list[str],
    channel_bindings: list[CommandChannelBinding],
) -> _StateTargetIdentity:
    return (
        capability_id,
        field_path,
        tuple(entity_ids),
        tuple(
            (
                binding.entity_id,
                binding.channel_id,
                binding.line_id,
                binding.capability,
                tuple(sorted(binding.group_ids)),
            )
            for binding in channel_bindings
        ),
    )


def _state_target_sort_key(identity: _StateTargetIdentity) -> str:
    return repr(identity)


def _validate_state_value(
    *,
    field_path: str,
    value: StateValue,
    spec: CapabilityField,
    payloads: dict[str, CommandPayload],
) -> list[Problem]:
    atom = spec.value_type.atom
    state_literal = value.root
    literal: object
    literal_path: ValuePath
    if isinstance(atom, BoolType):
        if not isinstance(state_literal, bool):
            return _field_value_mismatch(
                field_path,
                f"expected bool, got {_state_literal_type(state_literal)}",
            )
        literal = state_literal
        literal_path = ("value",)
    elif isinstance(atom, IntType):
        if not isinstance(state_literal, int) or isinstance(state_literal, bool):
            return _field_value_mismatch(
                field_path,
                f"expected int, got {_state_literal_type(state_literal)}",
            )
        literal = state_literal
        literal_path = ("value",)
    elif isinstance(atom, FloatType):
        if not isinstance(state_literal, int | float) or isinstance(
            state_literal, bool
        ):
            return _field_value_mismatch(
                field_path,
                f"expected float, got {_state_literal_type(state_literal)}",
            )
        literal = state_literal
        literal_path = ("value",)
    elif isinstance(atom, StringType):
        if not isinstance(state_literal, str):
            return _field_value_mismatch(
                field_path,
                f"expected string, got {_state_literal_type(state_literal)}",
            )
        literal = state_literal
        literal_path = ("value",)
    elif isinstance(atom, QuantityType):
        if not isinstance(state_literal, QuantityValue):
            return _field_value_mismatch(
                field_path,
                f"expected quantity, got {_state_literal_type(state_literal)}",
            )
        literal = state_literal
        literal_path = ("value",)
    elif isinstance(atom, PayloadType):
        if not isinstance(state_literal, PayloadRef):
            return _field_value_mismatch(
                field_path,
                f"expected payload reference, got {_state_literal_type(state_literal)}",
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
    else:  # CapabilityField validation makes this unreachable.
        raise AssertionError(type(atom).__name__)
    try:
        validate_literal(spec.value_type, literal, path=literal_path)
    except ValueValidationError as error:
        return _field_value_mismatch(
            field_path,
            error.reason,
            path=error.path,
        )
    return []


def _state_literal_type(value: StateLiteral) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, QuantityValue):
        return "quantity"
    return "payload reference"


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
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument_state_command", *path),
    )
