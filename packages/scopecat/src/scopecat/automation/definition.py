"""Versioned local procedure definitions and exact worker registries."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from textwrap import dedent
from types import MappingProxyType
from typing import Protocol, cast, get_type_hints, override

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from scopecat.automation.models import (
    ProcedureDefinitionRef,
    procedure_intent_hash,
)
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.records.content import Sha256ContentHash

_PROCEDURE_DEFINITION_FINGERPRINT_CODEC = "scopecat.procedure-definition.v1"
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue], config=ConfigDict(strict=True))
MAX_PROCEDURE_REGISTRY_SIZE = 200

type ProcedureFunction = Callable[..., None]
type ProcedureDefinitionKey = tuple[str, str]


class RegisteredProcedure(Protocol):
    """Type-erased executable contract retained by a heterogeneous registry."""

    @property
    def id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def intent_type(self) -> type[BaseModel]: ...

    @property
    def fingerprint(self) -> Sha256ContentHash: ...

    @property
    def ref(self) -> ProcedureDefinitionRef: ...

    def validate_intent(self, value: object) -> BaseModel: ...

    def encode_intent(self, value: object) -> dict[str, JsonValue]: ...

    def intent_hash(self, value: object) -> Sha256ContentHash: ...

    def run(self, context: object, intent: object) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class ProcedureDefinition[IntentT: BaseModel]:
    """One typed procedure implementation pinned to an explicit version."""

    id: str
    version: str
    intent_type: type[IntentT]
    _definition: ProcedureFunction = field(repr=False, compare=False)
    fingerprint: Sha256ContentHash = field(init=False)

    def __post_init__(self) -> None:
        _validate_definition_identity(self.id, self.version)
        _validate_intent_type(self.intent_type)
        _validate_procedure_function(self._definition, intent_type=self.intent_type)
        object.__setattr__(
            self,
            "fingerprint",
            _definition_fingerprint(
                id=self.id,
                version=self.version,
                intent_type=self.intent_type,
                definition=self._definition,
            ),
        )

    @property
    def ref(self) -> ProcedureDefinitionRef:
        """Return the durable identity pinned by a procedure run."""

        return ProcedureDefinitionRef(
            id=self.id,
            version=self.version,
            fingerprint=self.fingerprint,
        )

    @property
    def __wrapped__(self) -> ProcedureFunction:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return inspect.signature(self._definition)

    def validate_intent(self, value: object) -> IntentT:
        """Validate one caller value against the declared intent model."""

        return self.intent_type.model_validate(value, extra="forbid")

    def encode_intent(self, value: object) -> dict[str, JsonValue]:
        """Normalize one typed intent to the exact durable JSON document."""

        validated = self.validate_intent(value)
        return _JSON_OBJECT.validate_python(
            validated.model_dump(mode="json"),
            strict=True,
        )

    def intent_hash(self, value: object) -> Sha256ContentHash:
        """Hash this exact definition together with a normalized intent."""

        return procedure_intent_hash(self.ref, self.encode_intent(value))

    def run(self, context: object, intent: object) -> None:
        """Invoke the local implementation with a validated typed intent."""

        result = self._definition(context, self.validate_intent(intent))
        if result is not None:
            raise TypeError("procedure functions must return None")

    def __call__(self, context: object, intent: object) -> None:
        self.run(context, intent)


def procedure[IntentT: BaseModel](
    *,
    id: str,
    version: str,
    intent: type[IntentT],
) -> Callable[[ProcedureFunction], ProcedureDefinition[IntentT]]:
    """Decorate one ``(context, intent) -> None`` procedure function."""

    def decorate(definition: ProcedureFunction) -> ProcedureDefinition[IntentT]:
        return ProcedureDefinition(
            id=id,
            version=version,
            intent_type=intent,
            _definition=definition,
        )

    return decorate


class ProcedureRegistry(Mapping[ProcedureDefinitionKey, RegisteredProcedure]):
    """Immutable exact-version registry used by local procedure workers."""

    __slots__ = ("_definitions", "_refs")

    _definitions: Mapping[ProcedureDefinitionKey, RegisteredProcedure]
    _refs: tuple[ProcedureDefinitionRef, ...]

    def __init__(
        self,
        definitions: Iterable[RegisteredProcedure] = (),
    ) -> None:
        selected: dict[ProcedureDefinitionKey, RegisteredProcedure] = {}
        for definition in definitions:
            key = (definition.id, definition.version)
            if key in selected:
                raise ValueError(
                    f"procedure {definition.id!r} version "
                    f"{definition.version!r} is registered more than once"
                )
            if len(selected) >= MAX_PROCEDURE_REGISTRY_SIZE:
                raise ValueError(
                    "procedure registry supports at most "
                    f"{MAX_PROCEDURE_REGISTRY_SIZE} exact definitions"
                )
            selected[key] = definition
        ordered = dict(sorted(selected.items()))
        self._definitions = MappingProxyType(ordered)
        self._refs = tuple(definition.ref for definition in ordered.values())

    @property
    def refs(self) -> tuple[ProcedureDefinitionRef, ...]:
        """Return the deterministic durable catalog exposed by this registry."""

        return self._refs

    @override
    def __getitem__(
        self,
        key: ProcedureDefinitionKey,
    ) -> RegisteredProcedure:
        return self._definitions[key]

    @override
    def __iter__(self) -> Iterator[ProcedureDefinitionKey]:
        return iter(self._definitions)

    @override
    def __len__(self) -> int:
        return len(self._definitions)

    def require(self, id: str, version: str) -> RegisteredProcedure:
        """Load one exact local implementation with a useful missing error."""

        try:
            return self._definitions[(id, version)]
        except KeyError as error:
            raise LookupError(
                f"no procedure {id!r} version {version!r} is registered"
            ) from error

    def resolve(self, ref: ProcedureDefinitionRef) -> RegisteredProcedure:
        """Resolve a durable ref and reject a different local implementation."""

        definition = self.require(ref.id, ref.version)
        if definition.fingerprint != ref.fingerprint:
            raise ValueError(
                f"procedure {ref.id!r} version {ref.version!r} has fingerprint "
                f"{definition.fingerprint!r}, not {ref.fingerprint!r}"
            )
        return definition


def _validate_definition_identity(id: str, version: str) -> None:
    if not id.strip():
        raise ValueError("procedure id must be non-empty")
    if not version.strip():
        raise ValueError("procedure version must be non-empty")


def _validate_intent_type(intent_type: object) -> None:
    if not isinstance(intent_type, type) or not issubclass(intent_type, BaseModel):
        raise TypeError("procedure intent must be a Pydantic model type")
    if intent_type.model_config.get("frozen") is not True:
        raise TypeError("procedure intent models require frozen=True")


def _validate_procedure_function(
    definition: ProcedureFunction,
    *,
    intent_type: type[BaseModel],
) -> None:
    if not inspect.isfunction(definition):
        raise TypeError("procedure implementation must be a Python function")
    if inspect.iscoroutinefunction(definition):
        raise TypeError("procedure functions must be synchronous")
    signature = inspect.signature(definition)
    parameters = tuple(signature.parameters.values())
    if len(parameters) != 2 or any(
        parameter.kind
        not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        or cast("object", parameter.default) is not inspect.Parameter.empty
        for parameter in parameters
    ):
        raise TypeError("procedure functions require exactly (context, intent)")

    try:
        hints = get_type_hints(definition)
    except (NameError, TypeError) as error:
        raise TypeError("procedure function annotations must be resolvable") from error
    context_parameter, intent_parameter = parameters
    if context_parameter.name not in hints:
        raise TypeError("procedure context requires a type annotation")
    if hints.get(intent_parameter.name) is not intent_type:
        raise TypeError(
            "procedure intent annotation must match the declared intent model"
        )
    if hints.get("return", inspect.Signature.empty) is not type(None):
        raise TypeError("procedure functions must declare a None return type")


def _definition_fingerprint(
    *,
    id: str,
    version: str,
    intent_type: type[BaseModel],
    definition: ProcedureFunction,
) -> Sha256ContentHash:
    try:
        source = dedent(inspect.getsource(definition)).strip()
    except (OSError, TypeError) as error:
        raise TypeError(
            "procedure implementation source must be available to fingerprint"
        ) from error
    if not source:
        raise TypeError("procedure implementation source must be non-empty")

    identity = {
        "codec": _PROCEDURE_DEFINITION_FINGERPRINT_CODEC,
        "id": id,
        "version": version,
        "intent": {
            "module": intent_type.__module__,
            "qualname": intent_type.__qualname__,
            "schema": intent_type.model_json_schema(mode="validation"),
        },
        "implementation": {
            "module": definition.__module__,
            "qualname": definition.__qualname__,
            "source": source,
        },
    }
    return f"sha256:{stable_content_hash(identity)}"


__all__ = [
    "MAX_PROCEDURE_REGISTRY_SIZE",
    "ProcedureDefinition",
    "ProcedureDefinitionKey",
    "ProcedureFunction",
    "ProcedureRegistry",
    "RegisteredProcedure",
    "procedure",
]
