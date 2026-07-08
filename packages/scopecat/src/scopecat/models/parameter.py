"""Parameter and quantity models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.units import (
    compatible_units,
    from_base_value,
    is_supported_unit,
    to_base_value,
)


def _ensure_unique_ids[T: Any](items: list[T], label: str) -> list[T]:
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

    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str

    def __init__(
        self,
        value: float | None = None,
        unit: str | None = None,
        **data: Any,
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


class ParameterDefinition(BaseModel):
    """Stable physical or workflow parameter definition."""

    model_config = ConfigDict(extra="forbid")

    id: str
    unit: str
    safety_min: Quantity | None = None
    safety_max: Quantity | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        if not is_supported_unit(value):
            msg = f"unsupported unit: {value}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_safety_units(self) -> ParameterDefinition:
        for bound in (self.safety_min, self.safety_max):
            if bound is not None and not compatible_units(self.unit, bound.unit):
                msg = (
                    f"parameter definition {self.id} safety bound unit does not "
                    "match expected unit"
                )
                raise ValueError(msg)
        if (
            self.safety_min is not None
            and self.safety_max is not None
            and self.safety_min.value > self.safety_max.value
        ):
            msg = f"parameter {self.id} safety_min is greater than safety_max"
            raise ValueError(msg)
        return self


class ParameterValue(BaseModel):
    """Mutable value for a parameter definition."""

    model_config = ConfigDict(extra="forbid")

    id: str
    quantity: Quantity
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParameterValueSet(BaseModel):
    """Accepted scalar parameter values."""

    model_config = ConfigDict(extra="forbid")

    id: str
    values: list[ParameterValue]

    @field_validator("values")
    @classmethod
    def validate_values(cls, value: list[ParameterValue]) -> list[ParameterValue]:
        return _ensure_unique_ids(value, "parameter value")

    def get(self, value_id: str) -> ParameterValue | None:
        for value in self.values:
            if value.id == value_id:
                return value
        return None


ParameterTableColumnKind = Literal["quantity", "number", "string", "bool"]


class ParameterTableColumn(BaseModel):
    """Column schema for a table-shaped parameter source."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ParameterTableColumnKind
    unit: str | None = None
    required: bool = True
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unit(self) -> ParameterTableColumn:
        if self.kind == "quantity":
            if self.unit is None:
                msg = f"quantity column {self.id} requires a unit"
                raise ValueError(msg)
            if not is_supported_unit(self.unit):
                msg = f"unsupported unit: {self.unit}"
                raise ValueError(msg)
        elif self.unit is not None:
            msg = f"non-quantity column {self.id} cannot declare a unit"
            raise ValueError(msg)
        return self


class ParameterTableDefinition(BaseModel):
    """Schema for repeated table-shaped parameters."""

    model_config = ConfigDict(extra="forbid")

    id: str
    primary_key: list[str] = Field(min_length=1)
    columns: list[ParameterTableColumn]
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("columns")
    @classmethod
    def validate_columns(
        cls, value: list[ParameterTableColumn]
    ) -> list[ParameterTableColumn]:
        return _ensure_unique_ids(value, "parameter table column")

    @model_validator(mode="after")
    def validate_primary_key(self) -> ParameterTableDefinition:
        columns = {column.id for column in self.columns}
        missing = [
            column_id for column_id in self.primary_key if column_id not in columns
        ]
        if missing:
            msg = (
                f"parameter table {self.id} primary key references missing columns: "
                + ", ".join(missing)
            )
            raise ValueError(msg)
        if len(set(self.primary_key)) != len(self.primary_key):
            msg = f"parameter table {self.id} primary key contains duplicates"
            raise ValueError(msg)
        return self


class ParameterCatalog(BaseModel):
    """Authored parameter schema for scalar and table-shaped inputs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.parameter_catalog.v1"] = (
        "scopecat.parameter_catalog.v1"
    )
    id: str
    scalar_definitions: list[ParameterDefinition] = Field(default_factory=list)
    table_definitions: list[ParameterTableDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scalar_definitions")
    @classmethod
    def validate_scalar_definitions(
        cls, value: list[ParameterDefinition]
    ) -> list[ParameterDefinition]:
        return _ensure_unique_ids(value, "scalar parameter definition")

    @field_validator("table_definitions")
    @classmethod
    def validate_table_definitions(
        cls, value: list[ParameterTableDefinition]
    ) -> list[ParameterTableDefinition]:
        return _ensure_unique_ids(value, "parameter table definition")

    @model_validator(mode="after")
    def validate_namespace(self) -> ParameterCatalog:
        scalar_ids = {definition.id for definition in self.scalar_definitions}
        table_ids = {definition.id for definition in self.table_definitions}
        collisions = sorted(scalar_ids & table_ids)
        if collisions:
            msg = "parameter catalog has scalar/table id collisions: " + ", ".join(
                collisions
            )
            raise ValueError(msg)
        return self

    def scalar(self, definition_id: str) -> ParameterDefinition | None:
        for definition in self.scalar_definitions:
            if definition.id == definition_id:
                return definition
        return None

    def table(self, definition_id: str) -> ParameterTableDefinition | None:
        for definition in self.table_definitions:
            if definition.id == definition_id:
                return definition
        return None


class ParameterTable(BaseModel):
    """Accepted or computed values for a table-shaped parameter."""

    model_config = ConfigDict(extra="forbid")

    id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParameterState(BaseModel):
    """Accepted source parameter state for future runs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.parameter_state.v1"] = (
        "scopecat.parameter_state.v1"
    )
    id: str
    scalar_values: ParameterValueSet
    tables: list[ParameterTable] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tables")
    @classmethod
    def validate_tables(cls, value: list[ParameterTable]) -> list[ParameterTable]:
        return _ensure_unique_ids(value, "parameter table")

    def scalar_value_set(self) -> ParameterValueSet:
        return self.scalar_values


class ParameterViewSnapshot(BaseModel):
    """Resolved parameter values consumed by planning and execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.parameter_view_snapshot.v1"] = (
        "scopecat.parameter_view_snapshot.v1"
    )
    id: str
    catalog_id: str
    catalog_hash: str
    source_state_id: str
    source_state_hash: str
    derivation_set_id: str | None = None
    derivation_set_hash: str | None = None
    content_hash: str
    view_implementation_id: str
    view_implementation_version: str
    scalar_values: list[ParameterValue] = Field(default_factory=list)
    tables: list[ParameterTable] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scalar_values")
    @classmethod
    def validate_scalar_values(
        cls, value: list[ParameterValue]
    ) -> list[ParameterValue]:
        return _ensure_unique_ids(value, "parameter view scalar value")

    @field_validator("tables")
    @classmethod
    def validate_tables(cls, value: list[ParameterTable]) -> list[ParameterTable]:
        return _ensure_unique_ids(value, "parameter view table")

    def get(self, value_id: str) -> ParameterValue | None:
        for value in self.scalar_values:
            if value.id == value_id:
                return value
        return None

    def table(self, table_id: str) -> ParameterTable | None:
        for table in self.tables:
            if table.id == table_id:
                return table
        return None


ParameterPatchKind = Literal["set_scalar", "update_rows", "insert_rows", "delete_rows"]
ParameterPatchValue = Quantity | dict[str, Any] | str | float | int | bool | None


class ParameterPatch(BaseModel):
    """Concrete accepted-state patch used by experiments and config candidates."""

    model_config = ConfigDict(extra="forbid")

    kind: ParameterPatchKind
    parameter_id: str | None = None
    table_id: str | None = None
    key: dict[str, ParameterPatchValue] | None = None
    values: dict[str, ParameterPatchValue] | None = None
    value: ParameterPatchValue = None
    expected_value: ParameterPatchValue = None
    expected_values: dict[str, ParameterPatchValue] | None = None
    rows: list[dict[str, ParameterPatchValue]] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ParameterPatch:
        if self.kind == "set_scalar":
            if self.parameter_id is None:
                msg = "set_scalar requires parameter_id and value"
                raise ValueError(msg)
            if not isinstance(self.value, Quantity):
                msg = "set_scalar value must be a quantity"
                raise ValueError(msg)
            if self.expected_value is not None and not isinstance(
                self.expected_value, Quantity
            ):
                msg = "set_scalar expected_value must be a quantity when provided"
                raise ValueError(msg)
            if (
                self.table_id is not None
                or self.key is not None
                or self.values is not None
                or self.expected_values is not None
                or self.rows is not None
            ):
                msg = "set_scalar cannot reference a table row"
                raise ValueError(msg)
        elif self.kind == "update_rows":
            if self.table_id is None or self.key is None or self.values is None:
                msg = "update_rows requires table_id, key, and values"
                raise ValueError(msg)
            if (
                self.parameter_id is not None
                or self.value is not None
                or self.expected_value is not None
                or self.rows is not None
            ):
                msg = "update_rows cannot reference scalar or insert row fields"
                raise ValueError(msg)
        elif self.kind == "insert_rows":
            if self.table_id is None or not self.rows:
                msg = "insert_rows requires table_id and rows"
                raise ValueError(msg)
            if (
                self.parameter_id is not None
                or self.key is not None
                or self.values is not None
                or self.value is not None
                or self.expected_value is not None
                or self.expected_values is not None
            ):
                msg = "insert_rows cannot reference scalar or update/delete fields"
                raise ValueError(msg)
        elif self.kind == "delete_rows":
            if self.table_id is None or self.key is None:
                msg = "delete_rows requires table_id and key"
                raise ValueError(msg)
            if (
                self.parameter_id is not None
                or self.values is not None
                or self.value is not None
                or self.expected_value is not None
                or self.rows is not None
            ):
                msg = "delete_rows cannot reference scalar or value fields"
                raise ValueError(msg)
        return self


class ParameterChangeSet(BaseModel):
    """Named accepted-state parameter patch set produced by analysis or adapters."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.parameter_change_set.v1"] = (
        "scopecat.parameter_change_set.v1"
    )
    id: str
    source_run_id: str
    reason: str
    patches: list[ParameterPatch] = Field(min_length=1)
    confidence: float | None = None
