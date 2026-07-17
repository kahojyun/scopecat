"""Parameter and quantity models."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, Protocol, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_serializer,
    field_validator,
    model_validator,
)

from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping, thaw_json_value
from scopecat.kernel.problems import ExternalLocation
from scopecat.kernel.units import (
    compatible_units,
    from_base_value,
    is_supported_unit,
    to_base_value,
)
from scopecat.kernel.value_type_wire import (
    scalar_type_from_wire,
    scalar_type_to_wire,
    scalar_type_wire_schema,
)
from scopecat.kernel.value_types import (
    Bool as BoolType,
)
from scopecat.kernel.value_types import (
    Entity as EntityType,
)
from scopecat.kernel.value_types import (
    Float as FloatType,
)
from scopecat.kernel.value_types import (
    Int as IntType,
)
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)
from scopecat.kernel.value_types import (
    Scalar,
    Series,
    Table,
    TableColumn,
    ValueType,
)
from scopecat.kernel.value_types import (
    String as StringType,
)
from scopecat.records.entity import EntityRef, normalize_entity_metadata


class _Identified(Protocol):
    @property
    def id(self) -> str: ...


def _ensure_unique_ids[T: _Identified](items: list[T], label: str) -> list[T]:
    seen: set[str] = set()
    for item in items:
        item_id = item.id
        if item_id in seen:
            msg = f"duplicate {label} id: {item_id}"
            raise ValueError(msg)
        seen.add(item_id)
    return items


class Quantity(BaseModel):
    """A numeric value with an explicit unit."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    value: float
    unit: str

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> object:
        if not isinstance(value, int | float) or isinstance(value, bool):
            msg = "quantity value must be an int or float"
            raise ValueError(msg)
        return value

    def __init__(
        self,
        value: float | None = None,
        unit: str | None = None,
        **data: object,
    ) -> None:
        if value is not None:
            if "value" in data:
                msg = "Quantity value was provided twice"
                raise TypeError(msg)
            data["value"] = value
        if unit is not None:
            if "unit" in data:
                msg = "Quantity unit was provided twice"
                raise TypeError(msg)
            data["unit"] = unit
        super().__init__(**data)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        if not is_supported_unit(value):
            msg = f"unsupported unit: {value}"
            raise ValueError(msg)
        return value

    def to(self, unit: str) -> Quantity:
        """Return this quantity converted to another compatible linear unit."""

        if not is_supported_unit(unit):
            msg = f"unsupported unit: {unit}"
            raise ValueError(msg)
        if not compatible_units(self.unit, unit):
            msg = f"cannot convert {self.unit!r} to {unit!r}"
            raise ValueError(msg)
        base_value = to_base_value(self.value, self.unit)
        converted = None if base_value is None else from_base_value(base_value, unit)
        if converted is None:
            msg = f"unit conversion is not linear: {self.unit!r} to {unit!r}"
            raise ValueError(msg)
        return Quantity(value=round(converted, 12), unit=unit)

    def __add__(self, other: object) -> Quantity:
        if not isinstance(other, Quantity):
            return NotImplemented
        converted = other.to(self.unit)
        return Quantity(value=round(self.value + converted.value, 12), unit=self.unit)

    def __sub__(self, other: object) -> Quantity:
        if not isinstance(other, Quantity):
            return NotImplemented
        converted = other.to(self.unit)
        return Quantity(value=round(self.value - converted.value, 12), unit=self.unit)

    def __mul__(self, other: object) -> Quantity:
        if not isinstance(other, int | float) or isinstance(other, bool):
            return NotImplemented
        return Quantity(value=round(self.value * float(other), 12), unit=self.unit)

    def __rmul__(self, other: object) -> Quantity:
        return self.__mul__(other)

    def __truediv__(self, other: object) -> Quantity:
        if not isinstance(other, int | float) or isinstance(other, bool):
            return NotImplemented
        if other == 0:
            msg = "cannot divide quantity by zero"
            raise ZeroDivisionError(msg)
        return Quantity(value=round(self.value / float(other), 12), unit=self.unit)


_PERSISTABLE_SCALAR_WIRE_SCHEMA = scalar_type_wire_schema(
    ("bool", "int", "float", "string", "quantity", "entity"),
    finite_only=True,
)


def _persistable_value_type_schema() -> dict[str, object]:
    scalar = _PERSISTABLE_SCALAR_WIRE_SCHEMA
    scalar_shape = {
        "type": "object",
        "properties": {
            "shape": {"const": "scalar"},
            "atom": scalar,
        },
        "required": ["shape", "atom"],
        "additionalProperties": False,
    }
    series_shape = {
        "type": "object",
        "properties": {
            "shape": {"const": "series"},
            "item_type": scalar,
            "min_length": {"type": "integer", "minimum": 0},
            "max_length": {"type": ["integer", "null"], "minimum": 0},
        },
        "required": ["shape", "item_type"],
        "additionalProperties": False,
    }
    table_column = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "value_type": scalar,
            "required": {"type": "boolean"},
        },
        "required": ["id", "value_type"],
        "additionalProperties": False,
    }
    table_shape = {
        "type": "object",
        "properties": {
            "shape": {"const": "table"},
            "columns": {"type": "array", "items": table_column},
            "primary_key": {"type": "array", "items": {"type": "string"}},
            "min_rows": {"type": "integer", "minimum": 0},
            "max_rows": {"type": ["integer", "null"], "minimum": 0},
        },
        "required": ["shape", "columns"],
        "additionalProperties": False,
    }
    return {"oneOf": [scalar_shape, series_shape, table_shape]}


_PERSISTABLE_VALUE_TYPE_SCHEMA = _persistable_value_type_schema()


def _require_persistable_scalar_type(value: Scalar, *, path: str) -> Scalar:
    try:
        scalar_type_to_wire(value)
    except (TypeError, ValueError) as error:
        raise ValueError(str(error)) from error
    if not isinstance(
        value.atom,
        BoolType | IntType | FloatType | StringType | QuantityType | EntityType,
    ):
        msg = (
            f"{path} supports only bool, int, float, string, quantity, and entity atoms"
        )
        raise ValueError(msg)
    if isinstance(value.atom, FloatType | QuantityType) and not value.atom.finite:
        msg = f"{path} numeric atoms must require finite values"
        raise ValueError(msg)
    return value


def _validate_persistable_value_type(value: ValueType) -> ValueType:
    if isinstance(value, Scalar):
        return _require_persistable_scalar_type(value, path="persisted parameter")
    if isinstance(value, Series):
        _require_persistable_scalar_type(
            value.item_type,
            path="persisted parameter series item",
        )
        return value
    if value.allow_extra_columns:
        msg = "persisted parameter tables cannot allow untyped extra columns"
        raise ValueError(msg)
    for column in value.columns:
        _require_persistable_scalar_type(
            column.value_type,
            path=f"persisted parameter table column {column.id!r}",
        )
    return value


def _persistable_value_type_from_wire(value: object) -> ValueType:
    if isinstance(value, Scalar | Series | Table):
        return _validate_persistable_value_type(value)
    if not isinstance(value, Mapping):
        msg = "persisted parameter value_type must be an object"
        raise ValueError(msg)
    raw_data = dict(cast("Mapping[object, object]", value))
    if not all(isinstance(name, str) for name in raw_data):
        msg = "persisted parameter value_type field names must be strings"
        raise ValueError(msg)
    data = cast("dict[str, object]", raw_data)
    shape = data.pop("shape", None)
    try:
        if shape == "scalar":
            _require_exact_fields(data, required={"atom"}, optional=set())
            selected: ValueType = scalar_type_from_wire(data["atom"])
        elif shape == "series":
            _require_exact_fields(
                data,
                required={"item_type"},
                optional={"min_length", "max_length"},
            )
            selected = Series(
                item_type=scalar_type_from_wire(data["item_type"]),
                min_length=_wire_int(data.get("min_length", 0), "min_length"),
                max_length=_wire_optional_int(data.get("max_length"), "max_length"),
            )
        elif shape == "table":
            _require_exact_fields(
                data,
                required={"columns"},
                optional={"primary_key", "min_rows", "max_rows"},
            )
            raw_columns = data["columns"]
            if not isinstance(raw_columns, list):
                msg = "persisted parameter table columns must be a list"
                raise ValueError(msg)
            selected_columns = cast("list[object]", raw_columns)
            columns = tuple(
                _table_column_from_wire(column, index=index)
                for index, column in enumerate(selected_columns)
            )
            raw_primary_key = data.get("primary_key", [])
            if not isinstance(raw_primary_key, list) or not all(
                isinstance(column_id, str)
                for column_id in cast("list[object]", raw_primary_key)
            ):
                msg = "persisted parameter table primary_key must be a string list"
                raise ValueError(msg)
            selected = Table(
                columns=columns,
                primary_key=tuple(cast("list[str]", raw_primary_key)),
                min_rows=_wire_int(data.get("min_rows", 0), "min_rows"),
                max_rows=_wire_optional_int(data.get("max_rows"), "max_rows"),
            )
        else:
            msg = f"unsupported persisted parameter shape: {shape!r}"
            raise ValueError(msg)
    except (TypeError, ValueError) as error:
        msg = f"invalid persisted parameter value_type: {error}"
        raise ValueError(msg) from error
    return _validate_persistable_value_type(selected)


def _table_column_from_wire(value: object, *, index: int) -> TableColumn:
    if not isinstance(value, Mapping):
        msg = f"persisted parameter table column {index} must be an object"
        raise ValueError(msg)
    data = dict(cast("Mapping[object, object]", value))
    if not all(isinstance(name, str) for name in data):
        msg = f"persisted parameter table column {index} fields must be strings"
        raise ValueError(msg)
    _require_exact_fields(
        cast("dict[str, object]", data),
        required={"id", "value_type"},
        optional={"required"},
    )
    column_id = data["id"]
    required = data.get("required", True)
    if not isinstance(column_id, str) or not column_id:
        msg = f"persisted parameter table column {index} id must be non-empty"
        raise ValueError(msg)
    if not isinstance(required, bool):
        msg = f"persisted parameter table column {column_id!r} required must be bool"
        raise ValueError(msg)
    return TableColumn(
        id=column_id,
        value_type=scalar_type_from_wire(data["value_type"]),
        required=required,
    )


def _require_exact_fields(
    data: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str],
) -> None:
    missing = sorted(required - data.keys())
    if missing:
        msg = "missing fields: " + ", ".join(missing)
        raise ValueError(msg)
    extra = sorted(data.keys() - required - optional)
    if extra:
        msg = "unknown fields: " + ", ".join(extra)
        raise ValueError(msg)


def _wire_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{field_name} must be an integer"
        raise ValueError(msg)
    return value


def _wire_optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _wire_int(value, field_name)


def _persistable_value_type_to_wire(value: ValueType) -> dict[str, object]:
    selected = _validate_persistable_value_type(value)
    if isinstance(selected, Scalar):
        return {"shape": "scalar", "atom": scalar_type_to_wire(selected)}
    if isinstance(selected, Series):
        data: dict[str, object] = {
            "shape": "series",
            "item_type": scalar_type_to_wire(selected.item_type),
        }
        if selected.min_length:
            data["min_length"] = selected.min_length
        if selected.max_length is not None:
            data["max_length"] = selected.max_length
        return data
    data = {
        "shape": "table",
        "columns": [
            {
                "id": column.id,
                "value_type": scalar_type_to_wire(column.value_type),
                **({} if column.required else {"required": False}),
            }
            for column in selected.columns
        ],
    }
    if selected.primary_key:
        data["primary_key"] = list(selected.primary_key)
    if selected.min_rows:
        data["min_rows"] = selected.min_rows
    if selected.max_rows is not None:
        data["max_rows"] = selected.max_rows
    return data


type PersistableValueType = Annotated[
    ValueType,
    BeforeValidator(_persistable_value_type_from_wire),
    PlainSerializer(_persistable_value_type_to_wire, return_type=dict[str, object]),
    WithJsonSchema(_PERSISTABLE_VALUE_TYPE_SCHEMA, mode="validation"),
    WithJsonSchema(_PERSISTABLE_VALUE_TYPE_SCHEMA, mode="serialization"),
]


def _require_closed_parameter_atom_input(value: object) -> object:
    """Reject coercions from values outside the durable scalar domain."""

    if value is None or isinstance(
        value,
        Quantity | EntityRef | str | bool | int | float,
    ):
        return value
    if isinstance(value, Mapping):
        # Raw JSON objects are retained for Pydantic to validate as Quantity or
        # EntityRef. Freeze first so nested values cannot use Python-only
        # coercions (for example bytes -> string).
        return freeze_json_mapping(
            cast("Mapping[str, object]", value),
            path="persisted parameter scalar",
        )
    msg = (
        "persisted parameter scalar values must be quantity, entity, bool, int, "
        "float, string, or null"
    )
    raise ValueError(msg)


type ParameterAtomValue = Annotated[
    Quantity | EntityRef | bool | int | float | str | None,
    BeforeValidator(_require_closed_parameter_atom_input),
]


def _validate_finite_parameter_scalar(
    value: ParameterAtomValue,
) -> ParameterAtomValue:
    if isinstance(value, EntityRef):
        return value.model_copy(
            update={"metadata": normalize_entity_metadata(value.metadata)},
            deep=True,
        )
    number = value.value if isinstance(value, Quantity) else value
    if isinstance(number, float) and not math.isfinite(number):
        msg = "persisted parameter scalar values must be finite"
        raise ValueError(msg)
    return value


def _serialize_parameter_scalar(value: ParameterAtomValue) -> object:
    if isinstance(value, Quantity | EntityRef):
        return value.model_dump(mode="json")
    return value


class ParameterDefinition(BaseModel):
    """Stable type definition for one accepted parameter value."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    id: str
    value_type: PersistableValueType
    description: str | None = None
    metadata: Mapping[str, object] = Field(
        default_factory=lambda: FrozenMapping[str, object]()
    )

    @field_validator("value_type")
    @classmethod
    def validate_value_type(cls, value: ValueType) -> ValueType:
        return _validate_persistable_value_type(value)

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        return freeze_json_mapping(value, path="parameter definition metadata")

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, object]) -> object:
        return thaw_json_value(value)


class ParameterCatalog(BaseModel):
    """Authored parameter schema in one shape-independent namespace."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.parameter_catalog.v4"] = (
        "scopecat.parameter_catalog.v4"
    )
    id: str
    definitions: Sequence[ParameterDefinition] = Field(default_factory=tuple)
    metadata: Mapping[str, object] = Field(
        default_factory=lambda: FrozenMapping[str, object]()
    )

    @field_validator("definitions")
    @classmethod
    def validate_definitions(
        cls, value: Sequence[ParameterDefinition]
    ) -> Sequence[ParameterDefinition]:
        return tuple(_ensure_unique_ids(list(value), "parameter definition"))

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        return freeze_json_mapping(value, path="parameter catalog metadata")

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, object]) -> object:
        return thaw_json_value(value)

    def get(self, definition_id: str) -> ParameterDefinition | None:
        for definition in self.definitions:
            if definition.id == definition_id:
                return definition
        return None


class _StoredParameterValue(BaseModel):
    """Shared recursively immutable state for one stored parameter value."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        frozen=True,
        revalidate_instances="always",
    )

    id: str
    source_location: ExternalLocation | None = None
    metadata: Mapping[str, object] = Field(
        default_factory=lambda: FrozenMapping[str, object]()
    )

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata(
        cls,
        value: Mapping[str, object],
    ) -> Mapping[str, object]:
        return freeze_json_mapping(value, path="stored parameter metadata")

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, object]) -> object:
        return thaw_json_value(value)


class ScalarParameterValue(_StoredParameterValue):
    """One stored scalar parameter value."""

    shape: Literal["scalar"] = "scalar"
    value: ParameterAtomValue

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: ParameterAtomValue) -> ParameterAtomValue:
        return _validate_finite_parameter_scalar(value)


class SeriesParameterValue(_StoredParameterValue):
    """One stored ordered parameter series."""

    shape: Literal["series"] = "series"
    items: Sequence[ParameterAtomValue] = Field(default_factory=tuple)
    item_locations: Sequence[ExternalLocation] = Field(default_factory=tuple)

    @field_validator("items")
    @classmethod
    def validate_items(
        cls,
        value: Sequence[ParameterAtomValue],
    ) -> Sequence[ParameterAtomValue]:
        return tuple(_validate_finite_parameter_scalar(item) for item in value)

    @field_validator("item_locations")
    @classmethod
    def validate_item_locations(
        cls, value: Sequence[ExternalLocation]
    ) -> Sequence[ExternalLocation]:
        return tuple(value)

    @field_serializer("item_locations")
    def serialize_item_locations(
        self, value: Sequence[ExternalLocation]
    ) -> list[object]:
        return [location.model_dump(mode="json") for location in value]

    @model_validator(mode="after")
    def validate_location_count(self) -> Self:
        if self.item_locations and len(self.item_locations) != len(self.items):
            msg = "stored series item_locations must match items length"
            raise ValueError(msg)
        return self

    @field_serializer("items")
    def serialize_items(self, value: Sequence[ParameterAtomValue]) -> list[object]:
        return [_serialize_parameter_scalar(item) for item in value]


class TableParameterValue(_StoredParameterValue):
    """One stored typed table parameter."""

    shape: Literal["table"] = "table"
    rows: Sequence[Mapping[str, ParameterAtomValue]] = Field(default_factory=tuple)
    row_locations: Sequence[ExternalLocation] = Field(default_factory=tuple)

    @field_validator("rows")
    @classmethod
    def validate_rows(
        cls,
        value: Sequence[Mapping[str, ParameterAtomValue]],
    ) -> Sequence[Mapping[str, ParameterAtomValue]]:
        return tuple(
            FrozenMapping(
                (column_id, _validate_finite_parameter_scalar(cell))
                for column_id, cell in row.items()
            )
            for row in value
        )

    @field_validator("row_locations")
    @classmethod
    def validate_row_locations(
        cls, value: Sequence[ExternalLocation]
    ) -> Sequence[ExternalLocation]:
        return tuple(value)

    @field_serializer("row_locations")
    def serialize_row_locations(
        self, value: Sequence[ExternalLocation]
    ) -> list[object]:
        return [location.model_dump(mode="json") for location in value]

    @model_validator(mode="after")
    def validate_location_count(self) -> Self:
        if self.row_locations and len(self.row_locations) != len(self.rows):
            msg = "stored table row_locations must match rows length"
            raise ValueError(msg)
        return self

    @field_serializer("rows")
    def serialize_rows(
        self,
        value: Sequence[Mapping[str, ParameterAtomValue]],
    ) -> list[dict[str, object]]:
        return [
            {
                column_id: _serialize_parameter_scalar(cell)
                for column_id, cell in row.items()
            }
            for row in value
        ]


type StoredParameterValue = Annotated[
    ScalarParameterValue | SeriesParameterValue | TableParameterValue,
    Field(discriminator="shape"),
]


class ParameterSnapshot(BaseModel):
    """Recursively immutable accepted parameters for future runs."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.parameter_snapshot.v2"] = (
        "scopecat.parameter_snapshot.v2"
    )
    id: str
    values: Sequence[StoredParameterValue] = Field(default_factory=tuple)
    metadata: Mapping[str, object] = Field(
        default_factory=lambda: FrozenMapping[str, object]()
    )

    @field_validator("values")
    @classmethod
    def validate_values(
        cls,
        value: Sequence[StoredParameterValue],
    ) -> Sequence[StoredParameterValue]:
        return tuple(_ensure_unique_ids(list(value), "stored parameter value"))

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        return freeze_json_mapping(value, path="parameter snapshot metadata")

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, object]) -> object:
        return thaw_json_value(value)

    def get(self, value_id: str) -> StoredParameterValue | None:
        for value in self.values:
            if value.id == value_id:
                return value
        return None
