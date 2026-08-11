"""Validated JSON schemas for durable structured analysis facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from typing import cast, get_type_hints

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    create_model,
)

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.quantity import Quantity

SCALAR_FACT_SCHEMA_ID = "scopecat.scalar.v1"
QUANTITY_FACT_SCHEMA_ID = "scopecat.quantity.v1"

type ScalarFactValue = bool | int | float | str | None
type _FactEncoder[ValueT] = Callable[[ValueT], JsonValue]
type _FactDecoder[ValueT] = Callable[[JsonValue], ValueT]


def _schema_hash(schema: Mapping[str, object]) -> str:
    return f"sha256:{stable_content_hash(schema)}"


_SCALAR_ADAPTER: TypeAdapter[ScalarFactValue] = TypeAdapter(
    ScalarFactValue,
    config=ConfigDict(strict=True),
)
SCALAR_FACT_SCHEMA_HASH = _schema_hash(
    _SCALAR_ADAPTER.json_schema(mode="serialization")
)
QUANTITY_FACT_SCHEMA_HASH = _schema_hash(
    Quantity.model_json_schema(mode="serialization")
)


@dataclass(frozen=True, slots=True)
class AnalysisFactSchema[ValueT]:
    """Local validator for one versioned structured fact JSON contract.

    The durable record stores only ``id`` and ``schema_hash``. Callers keep the
    Python type local and provide the same descriptor when they want a typed
    value after reopening a run.
    """

    id: str
    value_type: type[ValueT]
    schema_hash: str = field(init=False)
    _encode: _FactEncoder[ValueT] = field(init=False, repr=False, compare=False)
    _decode: _FactDecoder[ValueT] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("analysis fact schema id must not be empty")
        schema, encoder, decoder = _fact_schema_adapter(self.id, self.value_type)
        object.__setattr__(self, "schema_hash", _schema_hash(schema))
        object.__setattr__(self, "_encode", encoder)
        object.__setattr__(self, "_decode", decoder)

    def encode(self, value: ValueT) -> JsonValue:
        """Validate and encode one typed value as canonical JSON content."""

        return self._encode(value)

    def decode(self, value: JsonValue) -> ValueT:
        """Validate durable JSON and reconstruct the caller's local type."""

        return self._decode(value)


def _fact_schema_adapter[ValueT](
    schema_id: str,
    value_type: type[ValueT],
) -> tuple[
    Mapping[str, object],
    _FactEncoder[ValueT],
    _FactDecoder[ValueT],
]:
    if issubclass(value_type, BaseModel):
        model_type = cast("type[BaseModel]", value_type)

        def encode_model(value: ValueT) -> JsonValue:
            if not isinstance(value, model_type):
                raise TypeError(
                    f"analysis fact schema {schema_id!r} requires "
                    f"{value_type.__qualname__}"
                )
            return cast(
                "JsonValue",
                model_type.model_validate(value).model_dump(mode="json"),
            )

        def decode_model(value: JsonValue) -> ValueT:
            return cast("ValueT", model_type.model_validate(value))

        return (
            cast(
                "Mapping[str, object]",
                model_type.model_json_schema(mode="serialization"),
            ),
            encode_model,
            decode_model,
        )

    if not is_dataclass(value_type):
        raise TypeError(
            "structured analysis fact schemas require a dataclass or "
            "Pydantic model type"
        )
    members = fields(value_type)
    if any(not member.init for member in members):
        raise TypeError("analysis fact dataclass fields must participate in init")
    hints = _dataclass_type_hints(value_type)
    definitions: dict[str, tuple[object, object]] = {}
    for member in members:
        if member.default_factory is not MISSING:
            default: object = Field(
                default_factory=cast("Callable[[], object]", member.default_factory)
            )
        elif member.default is not MISSING:
            default = cast("object", member.default)
        else:
            default = ...
        definitions[member.name] = (hints[member.name], default)
    model_factory = cast("Callable[..., type[BaseModel]]", create_model)
    validation_model = model_factory(
        "AnalysisFactValue",
        __config__=ConfigDict(
            title=schema_id,
            extra="forbid",
            strict=True,
        ),
        **definitions,
    )

    def encode_dataclass(value: ValueT) -> JsonValue:
        if not isinstance(value, value_type):
            raise TypeError(
                f"analysis fact schema {schema_id!r} requires {value_type.__qualname__}"
            )
        validated = validation_model.model_validate(value, from_attributes=True)
        return cast("JsonValue", validated.model_dump(mode="json"))

    def decode_dataclass(value: JsonValue) -> ValueT:
        validated = validation_model.model_validate(value)
        constructor = cast("Callable[..., ValueT]", value_type)
        return constructor(
            **{member.name: getattr(validated, member.name) for member in members}
        )

    return (
        cast(
            "Mapping[str, object]",
            validation_model.model_json_schema(mode="serialization"),
        ),
        encode_dataclass,
        decode_dataclass,
    )


def _dataclass_type_hints(value_type: type[object]) -> Mapping[str, object]:
    initializer = getattr(value_type, "__init__", None)
    retained_globals = getattr(initializer, "__globals__", None)
    globalns = cast(
        "dict[str, object] | None",
        retained_globals if isinstance(retained_globals, dict) else None,
    )
    # AnalysisField metadata describes dataset and view projection. It is not a
    # validation constraint on the structured fact's canonical JSON shape.
    return get_type_hints(
        value_type,
        globalns=globalns,
        include_extras=False,
    )


__all__ = [
    "QUANTITY_FACT_SCHEMA_HASH",
    "QUANTITY_FACT_SCHEMA_ID",
    "SCALAR_FACT_SCHEMA_HASH",
    "SCALAR_FACT_SCHEMA_ID",
    "AnalysisFactSchema",
    "ScalarFactValue",
]
