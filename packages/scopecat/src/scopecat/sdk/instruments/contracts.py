"""Instrument driver SDK."""

from __future__ import annotations

from collections.abc import Iterable
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
from scopecat.kernel.units import compatible_units
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
from scopecat.measurements.contracts import (
    measurement_value_contract_issues,
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
from scopecat.records.measurement import MeasurementArray
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
    label: str | None = None
    description: str | None = None
    access: Literal["read_only", "write_only", "read_write"] = "read_write"
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
    label: str | None = None
    description: str | None = None
    kind: str
    size: int | None = None
    unit: str | None = None


class ProductDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str | None = None
    description: str | None = None
    dtype: MeasurementDType = "float64"
    unit: str | None = None
    axes: list[ProductAxisDescription] = Field(default_factory=list)

    @field_validator("axes")
    @classmethod
    def validate_unique_axes(
        cls,
        value: list[ProductAxisDescription],
    ) -> list[ProductAxisDescription]:
        _require_unique(
            (axis.id for axis in value),
            "product axis ids",
        )
        return value


class CapabilityDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    description: str | None = None
    fields: list[CapabilityField] = Field(default_factory=list)
    products: list[ProductDescription] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_members(self) -> CapabilityDescription:
        _require_unique(
            (field.id for field in self.fields),
            "capability field ids",
        )
        _require_unique(
            (product.key for product in self.products),
            "capability product keys",
        )
        return self


class InstrumentDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    implementation_id: str
    implementation_version: str
    label: str | None = None
    description: str | None = None
    capabilities: list[CapabilityDescription] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_capabilities(self) -> InstrumentDescription:
        _require_unique(
            (capability.id for capability in self.capabilities),
            "instrument capability ids",
        )
        return self


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
    size: int = Field(gt=0)
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

    def close(self) -> None: ...

    def cleanup(self) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True)
class InstrumentProviderContext:
    config: ConfigProfileSnapshot
    instrument_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not instrument_id for instrument_id in self.instrument_ids):
            raise ValueError("provider instrument ids must be non-empty")
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise ValueError("provider instrument ids must be unique")


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
    label: str | None = None,
    description: str | None = None,
    fields: list[CapabilityField] | tuple[CapabilityField, ...] = (),
    products: list[ProductDescription] | tuple[ProductDescription, ...] = (),
) -> CapabilityDescription:
    return CapabilityDescription(
        id=id,
        label=label,
        description=description,
        fields=list(fields),
        products=list(products),
    )


def product_axis(
    id: str,
    *,
    size: int | None = None,
    kind: str | None = None,
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> ProductAxisDescription:
    return ProductAxisDescription(
        id=id,
        label=label,
        description=description,
        kind=kind or id,
        size=size,
        unit=unit,
    )


def product(
    key: str,
    *,
    dtype: MeasurementDType = "float64",
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
    axes: list[ProductAxisDescription] | tuple[ProductAxisDescription, ...] = (),
) -> ProductDescription:
    return ProductDescription(
        key=key,
        label=label,
        description=description,
        dtype=dtype,
        unit=unit,
        axes=list(axes),
    )


def quantity_field(
    id: str,
    *,
    unit: str,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> CapabilityField:
    return CapabilityField(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(QuantityType(unit=unit)),
    )


def bool_field(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> CapabilityField:
    return CapabilityField(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(BoolType()),
    )


def int_field(
    id: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> CapabilityField:
    return CapabilityField(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(IntType(minimum=minimum, maximum=maximum)),
    )


def float_field(
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> CapabilityField:
    return CapabilityField(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(FloatType()),
    )


def string_field(
    id: str,
    *,
    choices: tuple[str, ...] | None = None,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> CapabilityField:
    return CapabilityField(
        id=id,
        label=label,
        description=description,
        access=access,
        value_type=Scalar(StringType(choices=choices)),
    )


def enum_field(
    id: str,
    *,
    choices: tuple[str, ...],
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> CapabilityField:
    return string_field(
        id,
        choices=choices,
        label=label,
        description=description,
        access=access,
    )


def payload_field(
    id: str,
    *,
    schema_id: str,
    label: str | None = None,
    description: str | None = None,
    access: Literal["read_only", "write_only", "read_write"] = "read_write",
) -> CapabilityField:
    return CapabilityField(
        id=id,
        label=label,
        description=description,
        access=access,
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
        if field_spec.access == "read_only":
            problems.append(
                _problem(
                    "instrument_driver_read_only_field",
                    f"{command.instrument_id} field {field.field_path} is read-only",
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


def validate_collect_command(
    *,
    command: CollectCommand,
    description: InstrumentDescription,
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
    capabilities = {
        capability.id: capability for capability in description.capabilities
    }
    problems: list[Problem] = []
    for request in command.requests:
        capability_spec = capabilities.get(request.capability_id)
        if capability_spec is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_capability",
                    f"{command.instrument_id} does not support {request.capability_id}",
                    "requests",
                    request.id,
                    "capability_id",
                )
            )
            continue
        product_spec = next(
            (
                product
                for product in capability_spec.products
                if product.key == request.id
            ),
            None,
        )
        if product_spec is None:
            problems.append(
                _problem(
                    "instrument_driver_unsupported_product",
                    f"{command.instrument_id} does not support product "
                    f"{request.id} under {request.capability_id}",
                    "requests",
                    request.id,
                )
            )
            continue
        if request.dtype != product_spec.dtype:
            problems.append(
                _problem(
                    "instrument_driver_product_dtype_mismatch",
                    f"{command.instrument_id} product {request.id} requires "
                    f"dtype {product_spec.dtype}, got {request.dtype}",
                    "requests",
                    request.id,
                    "dtype",
                )
            )
        requested_unit = request.unit
        if requested_unit is not None and (
            product_spec.unit is None
            or not compatible_units(requested_unit, product_spec.unit)
        ):
            problems.append(
                _problem(
                    "instrument_driver_product_unit_mismatch",
                    f"{command.instrument_id} product {request.id} requires "
                    f"unit compatible with {product_spec.unit!r}, got "
                    f"{requested_unit!r}",
                    "requests",
                    request.id,
                    "unit",
                )
            )
        dimensions = request.dimensions
        dynamic_unspecified = (
            not dimensions
            and bool(product_spec.axes)
            and all(axis.size is None for axis in product_spec.axes)
        )
        if dynamic_unspecified:
            continue
        if len(dimensions) != len(product_spec.axes):
            problems.append(
                _problem(
                    "instrument_driver_product_axes_mismatch",
                    f"{command.instrument_id} product {request.id} axes do not "
                    "match its declared contract",
                    "requests",
                    request.id,
                    "dimensions",
                )
            )
            continue
        for axis_index, (requested_axis, declared_axis) in enumerate(
            zip(dimensions, product_spec.axes, strict=True)
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
                        "instrument_driver_product_axis_mismatch",
                        f"{command.instrument_id} product {request.id} axis "
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
                        "instrument_driver_product_axis_unit_mismatch",
                        f"{command.instrument_id} product {request.id} axis "
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
    for product_id in sorted(set(requests) - set(values)):
        problems.append(
            _problem(
                "instrument_driver_missing_product",
                f"{command.instrument_id} did not return requested product "
                f"{product_id}",
                "readback",
                "values",
                product_id,
            )
        )
    for product_id in sorted(set(values) - set(requests)):
        problems.append(
            _problem(
                "instrument_driver_unexpected_product",
                f"{command.instrument_id} returned unexpected product {product_id}",
                "readback",
                "values",
                product_id,
            )
        )
    for product_id in sorted(set(requests) & set(values)):
        request = requests[product_id]
        value = values[product_id]
        expected_shape = (
            tuple(axis.size for axis in request.dimensions)
            if request.dimensions
            else (tuple(value.shape) if isinstance(value, MeasurementArray) else ())
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
                    f"{command.instrument_id} product {product_id} violates "
                    f"its requested {issue.code.value} contract",
                    "readback",
                    "values",
                    product_id,
                    *issue.path,
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


def _require_unique(values: Iterable[str], label: str) -> None:
    selected = tuple(values)
    if len(selected) != len(set(selected)):
        raise ValueError(f"{label} must be unique")


def _problem(code: str, message: str, *path: LocationPathItem) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument_state_command", *path),
    )
