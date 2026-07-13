"""Stable wire encoding for durable scalar value type declarations."""

from __future__ import annotations

import math
from typing import Annotated, Literal, cast

from pydantic import BeforeValidator, PlainSerializer, TypeAdapter

from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Scalar,
    String,
)

type ScalarWireAtomName = Literal[
    "bool",
    "int",
    "float",
    "string",
    "quantity",
    "entity",
    "payload",
]

_SCALAR_WIRE_FIELDS: dict[ScalarWireAtomName, frozenset[str]] = {
    "bool": frozenset(),
    "int": frozenset({"minimum", "maximum"}),
    "float": frozenset({"minimum", "maximum", "finite"}),
    "string": frozenset({"min_length", "max_length", "pattern", "choices"}),
    "quantity": frozenset({"dimension", "unit", "minimum", "maximum", "finite"}),
    "entity": frozenset({"entity_kind"}),
    "payload": frozenset({"schema_id"}),
}


def scalar_type_wire_schema(
    atom_names: tuple[ScalarWireAtomName, ...],
    *,
    finite_only: bool = False,
    allow_nullable: bool = True,
) -> dict[str, object]:
    """Build the exact JSON schema for an allowed set of scalar atoms."""

    finite_schema: dict[str, object] = {"type": "boolean"}
    if finite_only:
        finite_schema["const"] = True
    nullable_schema: dict[str, object] = {"type": "boolean"}
    if not allow_nullable:
        nullable_schema["const"] = False
    variants: dict[ScalarWireAtomName, dict[str, object]] = {
        "bool": _scalar_wire_variant("bool", {}, nullable_schema=nullable_schema),
        "int": _scalar_wire_variant(
            "int",
            {
                "minimum": {"type": "integer"},
                "maximum": {"type": "integer"},
            },
            nullable_schema=nullable_schema,
        ),
        "float": _scalar_wire_variant(
            "float",
            {
                "minimum": {"type": "number"},
                "maximum": {"type": "number"},
                "finite": finite_schema,
            },
            nullable_schema=nullable_schema,
        ),
        "string": _scalar_wire_variant(
            "string",
            {
                "min_length": {"type": "integer", "minimum": 0},
                "max_length": {"type": "integer", "minimum": 0},
                "pattern": {"type": "string"},
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "uniqueItems": True,
                },
            },
            nullable_schema=nullable_schema,
        ),
        "quantity": _scalar_wire_variant(
            "quantity",
            {
                "dimension": {"type": "string"},
                "unit": {"type": "string"},
                "minimum": {"type": "number"},
                "maximum": {"type": "number"},
                "finite": finite_schema,
            },
            nullable_schema=nullable_schema,
            dependent_required={
                "minimum": ("unit",),
                "maximum": ("unit",),
            },
        ),
        "entity": _scalar_wire_variant(
            "entity",
            {"entity_kind": {"type": "string", "minLength": 1}},
            nullable_schema=nullable_schema,
        ),
        "payload": _scalar_wire_variant(
            "payload",
            {"schema_id": {"type": "string", "minLength": 1}},
            required=("schema_id",),
            nullable_schema=nullable_schema,
        ),
    }
    return {"oneOf": [variants[atom_name] for atom_name in atom_names]}


def scalar_type_from_wire(value: object) -> Scalar:
    """Decode and canonicalize a durable scalar type declaration."""

    if isinstance(value, Scalar):
        try:
            value = scalar_type_to_wire(value)
        except (TypeError, ValueError) as error:
            raise ValueError(str(error)) from error
    if not isinstance(value, dict):
        msg = "scalar value_type must be an object"
        raise ValueError(msg)
    raw_data = cast("dict[object, object]", value)
    data: dict[str, object] = {}
    for field_name, field_value in raw_data.items():
        if not isinstance(field_name, str):
            msg = f"scalar value_type field names must be strings, got {field_name!r}"
            raise ValueError(msg)
        data[field_name] = field_value
    atom_name = data.pop("type", None)
    nullable = data.pop("nullable", False)
    if not isinstance(nullable, bool):
        msg = "scalar value_type nullable must be a bool"
        raise ValueError(msg)
    if not isinstance(atom_name, str) or atom_name not in _SCALAR_WIRE_FIELDS:
        msg = f"unsupported scalar type: {atom_name!r}"
        raise ValueError(msg)
    selected_atom_name = atom_name
    allowed_fields = _SCALAR_WIRE_FIELDS[selected_atom_name]
    extra_fields = sorted(set(data) - allowed_fields)
    if extra_fields:
        msg = f"scalar type {atom_name!r} contains unknown fields: " + ", ".join(
            extra_fields
        )
        raise ValueError(msg)
    _validate_wire_field_types(selected_atom_name, data)
    try:
        if atom_name == "bool":
            atom = TypeAdapter(Bool).validate_python(data)
        elif atom_name == "int":
            atom = TypeAdapter(Int).validate_python(data)
        elif atom_name == "float":
            atom = TypeAdapter(Float).validate_python(data)
        elif atom_name == "string":
            atom = TypeAdapter(String).validate_python(data)
        elif atom_name == "quantity":
            atom = TypeAdapter(Quantity).validate_python(data)
        elif atom_name == "entity":
            atom = TypeAdapter(Entity).validate_python(data)
        elif atom_name == "payload":
            atom = TypeAdapter(Payload).validate_python(data)
        else:  # Covered by the allowed-fields lookup above.
            raise AssertionError(atom_name)
    except (TypeError, ValueError) as error:
        msg = f"invalid {atom_name!r} scalar type: {error}"
        raise ValueError(msg) from error
    return Scalar(atom=atom, nullable=nullable)


def scalar_type_to_wire(value: Scalar) -> dict[str, object]:
    """Encode a scalar type using the stable, flat wire representation."""

    _validate_scalar_type_declaration(value)
    atom = value.atom
    data: dict[str, object]
    if isinstance(atom, Bool):
        data = {"type": "bool"}
    elif isinstance(atom, Int):
        data = {"type": "int"}
        if atom.minimum is not None:
            data["minimum"] = atom.minimum
        if atom.maximum is not None:
            data["maximum"] = atom.maximum
    elif isinstance(atom, Float):
        data = {"type": "float"}
        if atom.minimum is not None:
            data["minimum"] = atom.minimum
        if atom.maximum is not None:
            data["maximum"] = atom.maximum
        if not atom.finite:
            data["finite"] = False
    elif isinstance(atom, String):
        data = {"type": "string"}
        if atom.min_length:
            data["min_length"] = atom.min_length
        if atom.max_length is not None:
            data["max_length"] = atom.max_length
        if atom.pattern is not None:
            data["pattern"] = atom.pattern
        if atom.choices is not None:
            data["choices"] = list(atom.choices)
    elif isinstance(atom, Quantity):
        data = {"type": "quantity"}
        if atom.dimension is not None:
            data["dimension"] = atom.dimension
        if atom.unit is not None:
            data["unit"] = atom.unit
        if atom.minimum is not None:
            data["minimum"] = atom.minimum
        if atom.maximum is not None:
            data["maximum"] = atom.maximum
        if not atom.finite:
            data["finite"] = False
    elif isinstance(atom, Entity):
        data = {"type": "entity"}
        if atom.entity_kind is not None:
            data["entity_kind"] = atom.entity_kind
    elif isinstance(atom, Payload):
        if atom.python_type is not None:
            msg = (
                "payload scalar type python_type is runtime-only and cannot be "
                "serialized"
            )
            raise TypeError(msg)
        data = {"type": "payload", "schema_id": atom.schema_id}
    else:
        msg = f"unsupported durable scalar type: {type(atom).__name__}"
        raise TypeError(msg)
    if value.nullable:
        data["nullable"] = True
    return data


type ScalarWire = Annotated[
    Scalar,
    BeforeValidator(scalar_type_from_wire),
    PlainSerializer(scalar_type_to_wire, return_type=dict[str, object]),
]


def _validate_wire_field_types(
    atom_name: ScalarWireAtomName,
    data: dict[str, object],
) -> None:
    integer_fields: tuple[str, ...] = ()
    number_fields: tuple[str, ...] = ()
    string_fields: tuple[str, ...] = ()
    if atom_name == "int":
        integer_fields = ("minimum", "maximum")
    elif atom_name == "float":
        number_fields = ("minimum", "maximum")
    elif atom_name == "string":
        integer_fields = ("min_length", "max_length")
        string_fields = ("pattern",)
    elif atom_name == "quantity":
        number_fields = ("minimum", "maximum")
        string_fields = ("dimension", "unit")
    elif atom_name == "entity":
        string_fields = ("entity_kind",)
    elif atom_name == "payload":
        string_fields = ("schema_id",)

    for field_name in integer_fields:
        field_value = data.get(field_name)
        if field_name in data and not _is_json_integer(field_value):
            _raise_wire_field_type(atom_name, field_name, "an integer")
    for field_name in number_fields:
        field_value = data.get(field_name)
        if field_name in data and (
            not isinstance(field_value, int | float) or isinstance(field_value, bool)
        ):
            _raise_wire_field_type(atom_name, field_name, "a number")
    for field_name in string_fields:
        if field_name in data and not isinstance(data[field_name], str):
            _raise_wire_field_type(atom_name, field_name, "a string")
    if "finite" in data and not isinstance(data["finite"], bool):
        _raise_wire_field_type(atom_name, "finite", "a bool")
    if "choices" in data:
        choices = data["choices"]
        if not isinstance(choices, list):
            _raise_wire_field_type(atom_name, "choices", "a list of strings")
        selected_choices = cast("list[object]", choices)
        if not all(isinstance(choice, str) for choice in selected_choices):
            _raise_wire_field_type(atom_name, "choices", "a list of strings")


def _validate_scalar_type_declaration(value: Scalar) -> None:
    _require_bool(value.nullable, label="scalar value_type nullable")
    atom = value.atom
    if isinstance(atom, Bool):
        return
    elif isinstance(atom, Int):
        _require_optional_int(atom.minimum, label="Int minimum")
        _require_optional_int(atom.maximum, label="Int maximum")
    elif isinstance(atom, Float):
        _require_optional_number(atom.minimum, label="Float minimum")
        _require_optional_number(atom.maximum, label="Float maximum")
        _require_bool(atom.finite, label="Float finite")
    elif isinstance(atom, String):
        _require_int(atom.min_length, label="String min_length")
        _require_optional_int(atom.max_length, label="String max_length")
        _require_optional_string(atom.pattern, label="String pattern")
        _require_optional_string_tuple(atom.choices, label="String choices")
    elif isinstance(atom, Quantity):
        _require_optional_string(atom.dimension, label="Quantity dimension")
        _require_optional_string(atom.unit, label="Quantity unit")
        _require_optional_number(atom.minimum, label="Quantity minimum")
        _require_optional_number(atom.maximum, label="Quantity maximum")
        _require_bool(atom.finite, label="Quantity finite")
    elif isinstance(atom, Entity):
        _require_optional_string(atom.entity_kind, label="Entity entity_kind")
    elif isinstance(atom, Payload):
        _require_string(atom.schema_id, label="Payload schema_id")
    else:
        msg = f"unsupported durable scalar type: {type(atom).__name__}"
        raise TypeError(msg)


def _require_bool(value: object, *, label: str) -> None:
    if not isinstance(value, bool):
        msg = f"{label} must be a bool"
        raise TypeError(msg)


def _require_int(value: object, *, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{label} must be an int"
        raise TypeError(msg)


def _require_optional_int(value: object, *, label: str) -> None:
    if value is not None:
        _require_int(value, label=label)


def _require_optional_number(value: object, *, label: str) -> None:
    if value is not None and (
        not isinstance(value, int | float) or isinstance(value, bool)
    ):
        msg = f"{label} must be an int or float"
        raise TypeError(msg)
    if value is None:
        return
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        msg = f"{label} must be a finite, representable number"
        raise TypeError(msg)


def _require_string(value: object, *, label: str) -> None:
    if not isinstance(value, str):
        msg = f"{label} must be a string"
        raise TypeError(msg)


def _require_optional_string(value: object, *, label: str) -> None:
    if value is not None:
        _require_string(value, label=label)


def _require_optional_string_tuple(value: object, *, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, tuple):
        msg = f"{label} must be a tuple of strings"
        raise TypeError(msg)
    selected = cast("tuple[object, ...]", value)
    if not all(isinstance(item, str) for item in selected):
        msg = f"{label} must be a tuple of strings"
        raise TypeError(msg)


def _is_json_integer(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value) and value.is_integer()


def _raise_wire_field_type(
    atom_name: ScalarWireAtomName,
    field_name: str,
    expected: str,
) -> None:
    msg = f"scalar type {atom_name!r} field {field_name!r} must be {expected}"
    raise ValueError(msg)


def _scalar_wire_variant(
    atom_name: ScalarWireAtomName,
    properties: dict[str, object],
    *,
    nullable_schema: dict[str, object],
    required: tuple[str, ...] = (),
    dependent_required: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, object]:
    variant: dict[str, object] = {
        "type": "object",
        "required": ["type", *required],
        "additionalProperties": False,
        "properties": {
            "type": {"type": "string", "const": atom_name},
            "nullable": nullable_schema,
            **properties,
        },
    }
    if dependent_required:
        variant["dependentRequired"] = {
            field_name: list(dependencies)
            for field_name, dependencies in dependent_required.items()
        }
    return variant


__all__ = [
    "ScalarWire",
    "ScalarWireAtomName",
    "scalar_type_from_wire",
    "scalar_type_to_wire",
    "scalar_type_wire_schema",
]
