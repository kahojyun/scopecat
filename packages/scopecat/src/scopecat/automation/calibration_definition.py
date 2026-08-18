"""Typed project-owned calibration definitions and immutable registries."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from textwrap import dedent
from types import MappingProxyType
from typing import Protocol, cast, get_type_hints, override

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.automation.calibrations import (
    MAX_CALIBRATION_COHORT_MEMBERS,
    CalibrationDefinitionRef,
    CalibrationDependencyEvidence,
    CalibrationTargetRef,
    calibration_key,
)
from scopecat.automation.definition import ProcedureDefinition, RegisteredProcedure
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.records.content import Sha256ContentHash

_CALIBRATION_DEFINITION_FINGERPRINT_CODEC = "scopecat.calibration-definition.v1"
_CALIBRATION_INPUT_FINGERPRINT_CODEC = "scopecat.calibration-input.v1"
MAX_CALIBRATION_REGISTRY_SIZE = 200


class CalibrationDependencyRequirement(BaseModel):
    """Logical calibration whose latest prior success is required as evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    definition_id: str
    target: CalibrationTargetRef

    @field_validator("definition_id")
    @classmethod
    def validate_definition_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("calibration dependency definition id must be non-empty")
        return value

    @property
    def calibration_key(self) -> str:
        return calibration_key(self.definition_id, self.target)


class CalibrationObservation[InputsT: BaseModel](BaseModel):
    """Typed member inputs and logical dependencies observed from one snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inputs: InputsT
    dependencies: tuple[CalibrationDependencyRequirement, ...] = Field(
        default=(),
        max_length=MAX_CALIBRATION_COHORT_MEMBERS,
    )
    valid_for: timedelta | None = None

    @field_validator("valid_for")
    @classmethod
    def validate_valid_for(cls, value: timedelta | None) -> timedelta | None:
        if value is not None and value <= timedelta(0):
            raise ValueError("calibration freshness duration must be positive")
        return value

    @model_validator(mode="after")
    def validate_dependencies(self) -> CalibrationObservation[InputsT]:
        keys = tuple(item.calibration_key for item in self.dependencies)
        if len(keys) != len(set(keys)):
            raise ValueError("calibration dependency keys must be unique")
        return self


class RegisteredCalibration[ContextT](Protocol):
    """Type-erased calibration retained by a heterogeneous project registry."""

    @property
    def id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def ref(self) -> CalibrationDefinitionRef: ...

    @property
    def procedure(self) -> RegisteredProcedure: ...

    @property
    def fanout_scope(self) -> str: ...

    @property
    def max_in_flight(self) -> int: ...

    def select_targets(self, context: ContextT) -> tuple[CalibrationTargetRef, ...]: ...

    def observe(
        self,
        context: ContextT,
        target: CalibrationTargetRef,
    ) -> CalibrationObservation[BaseModel]: ...

    def input_fingerprint(self, inputs: BaseModel) -> Sha256ContentHash: ...

    def build_intent(
        self,
        context: ContextT,
        target: CalibrationTargetRef,
        inputs: BaseModel,
        dependencies: tuple[CalibrationDependencyEvidence, ...],
    ) -> BaseModel: ...


@dataclass(frozen=True, slots=True, repr=False)
class CalibrationDefinition[ContextT, InputsT: BaseModel, IntentT: BaseModel]:
    """One typed project policy for freshness evaluation and bounded fan-out."""

    id: str
    version: str
    input_type: type[InputsT]
    procedure: ProcedureDefinition[IntentT]
    fanout_scope: str
    max_in_flight: int
    _select_targets: Callable[[ContextT], tuple[CalibrationTargetRef, ...]] = field(
        repr=False,
        compare=False,
    )
    _observe: Callable[
        [ContextT, CalibrationTargetRef], CalibrationObservation[InputsT]
    ] = field(repr=False, compare=False)
    _build_intent: Callable[
        [
            ContextT,
            CalibrationTargetRef,
            InputsT,
            tuple[CalibrationDependencyEvidence, ...],
        ],
        IntentT,
    ] = field(repr=False, compare=False)
    fingerprint: Sha256ContentHash = field(init=False)

    def __post_init__(self) -> None:
        _require_non_blank(self.id, field_name="calibration definition id")
        _require_non_blank(self.version, field_name="calibration definition version")
        _require_non_blank(self.fanout_scope, field_name="calibration fanout scope")
        if not 1 <= self.max_in_flight <= MAX_CALIBRATION_COHORT_MEMBERS:
            raise ValueError(
                "calibration max_in_flight must be between 1 and "
                f"{MAX_CALIBRATION_COHORT_MEMBERS}"
            )
        _validate_model_type(self.input_type, label="calibration input")
        _validate_selector(self._select_targets)
        _validate_observer(self._observe, self.input_type)
        _validate_intent_builder(
            self._build_intent,
            input_type=self.input_type,
            intent_type=self.procedure.intent_type,
        )
        object.__setattr__(
            self,
            "fingerprint",
            _calibration_definition_fingerprint(
                id=self.id,
                version=self.version,
                input_type=self.input_type,
                procedure=self.procedure,
                fanout_scope=self.fanout_scope,
                max_in_flight=self.max_in_flight,
                selector=self._select_targets,
                observer=self._observe,
                builder=self._build_intent,
            ),
        )

    @property
    def ref(self) -> CalibrationDefinitionRef:
        return CalibrationDefinitionRef(
            id=self.id,
            version=self.version,
            fingerprint=self.fingerprint,
        )

    def select_targets(self, context: ContextT) -> tuple[CalibrationTargetRef, ...]:
        selected = self._select_targets(context)
        if len(selected) > MAX_CALIBRATION_COHORT_MEMBERS:
            raise ValueError(
                "calibration selector supports at most "
                f"{MAX_CALIBRATION_COHORT_MEMBERS} targets"
            )
        keys = tuple((item.kind, item.id) for item in selected)
        if len(keys) != len(set(keys)):
            raise ValueError("calibration selector targets must be unique")
        return tuple(sorted(selected, key=lambda item: (item.kind, item.id)))

    def observe(
        self,
        context: ContextT,
        target: CalibrationTargetRef,
    ) -> CalibrationObservation[BaseModel]:
        observed = self._observe(context, target)
        inputs = self.input_type.model_validate(observed.inputs, extra="forbid")
        return cast(
            "CalibrationObservation[BaseModel]",
            observed.model_copy(update={"inputs": inputs}),
        )

    def input_fingerprint(self, inputs: BaseModel) -> Sha256ContentHash:
        selected = self.input_type.model_validate(inputs, extra="forbid")
        digest = stable_content_hash(
            {
                "codec": _CALIBRATION_INPUT_FINGERPRINT_CODEC,
                "inputs": selected.model_dump(mode="json"),
            }
        )
        return f"sha256:{digest}"

    def build_intent(
        self,
        context: ContextT,
        target: CalibrationTargetRef,
        inputs: BaseModel,
        dependencies: tuple[CalibrationDependencyEvidence, ...],
    ) -> IntentT:
        selected = self.input_type.model_validate(inputs, extra="forbid")
        return self.procedure.validate_intent(
            self._build_intent(context, target, selected, dependencies)
        )


def calibration[
    ContextT,
    InputsT: BaseModel,
    IntentT: BaseModel,
](
    *,
    id: str,
    version: str,
    inputs: type[InputsT],
    procedure: ProcedureDefinition[IntentT],
    fanout_scope: str,
    max_in_flight: int,
    select: Callable[[ContextT], tuple[CalibrationTargetRef, ...]],
    observe: Callable[
        [ContextT, CalibrationTargetRef], CalibrationObservation[InputsT]
    ],
) -> Callable[
    [
        Callable[
            [
                ContextT,
                CalibrationTargetRef,
                InputsT,
                tuple[CalibrationDependencyEvidence, ...],
            ],
            IntentT,
        ]
    ],
    CalibrationDefinition[ContextT, InputsT, IntentT],
]:
    """Decorate a snapshot-bound intent builder with its selector and observer."""

    def decorate(
        builder: Callable[
            [
                ContextT,
                CalibrationTargetRef,
                InputsT,
                tuple[CalibrationDependencyEvidence, ...],
            ],
            IntentT,
        ],
    ) -> CalibrationDefinition[ContextT, InputsT, IntentT]:
        return CalibrationDefinition(
            id=id,
            version=version,
            input_type=inputs,
            procedure=procedure,
            fanout_scope=fanout_scope,
            max_in_flight=max_in_flight,
            _select_targets=select,
            _observe=observe,
            _build_intent=builder,
        )

    return decorate


class CalibrationRegistry[ContextT](Mapping[str, RegisteredCalibration[ContextT]]):
    """Immutable registry with one active version per logical calibration ID."""

    __slots__ = ("_definitions",)

    _definitions: Mapping[str, RegisteredCalibration[ContextT]]

    def __init__(
        self,
        definitions: Iterable[RegisteredCalibration[ContextT]] = (),
    ) -> None:
        selected: dict[str, RegisteredCalibration[ContextT]] = {}
        for definition in definitions:
            if definition.id in selected:
                existing = selected[definition.id]
                raise ValueError(
                    f"calibration {definition.id!r} has more than one active version "
                    f"({existing.version!r} and {definition.version!r})"
                )
            if len(selected) >= MAX_CALIBRATION_REGISTRY_SIZE:
                raise ValueError(
                    "calibration registry supports at most "
                    f"{MAX_CALIBRATION_REGISTRY_SIZE} definitions"
                )
            selected[definition.id] = definition
        self._definitions = MappingProxyType(dict(sorted(selected.items())))

    @override
    def __getitem__(self, key: str) -> RegisteredCalibration[ContextT]:
        return self._definitions[key]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._definitions)

    @override
    def __len__(self) -> int:
        return len(self._definitions)

    def require(self, id: str) -> RegisteredCalibration[ContextT]:
        try:
            return self._definitions[id]
        except KeyError as error:
            raise LookupError(f"no calibration {id!r} is registered") from error

    def resolve(
        self,
        ref: CalibrationDefinitionRef,
    ) -> RegisteredCalibration[ContextT]:
        definition = self.require(ref.id)
        if definition.ref != ref:
            raise ValueError(
                f"calibration {ref.id!r} does not match exact version/fingerprint"
            )
        return definition


def _validate_model_type(value: object, *, label: str) -> None:
    if not isinstance(value, type) or not issubclass(value, BaseModel):
        raise TypeError(f"{label} must be a Pydantic model type")
    if value.model_config.get("frozen") is not True:
        raise TypeError(f"{label} models require frozen=True")


def _validate_selector(selector: Callable[..., object]) -> None:
    parameters, hints = _validate_function(selector, label="calibration selector")
    if len(parameters) != 1:
        raise TypeError("calibration selector requires exactly (context)")
    if parameters[0].name not in hints:
        raise TypeError("calibration selector context requires an annotation")
    if hints.get("return") != tuple[CalibrationTargetRef, ...]:
        raise TypeError(
            "calibration selector return annotation must be "
            "tuple[CalibrationTargetRef, ...]"
        )


def _validate_observer(
    observer: Callable[..., object],
    input_type: type[BaseModel],
) -> None:
    parameters, hints = _validate_function(observer, label="calibration observer")
    if len(parameters) != 2:
        raise TypeError("calibration observer requires exactly (context, target)")
    context, target = parameters
    if context.name not in hints:
        raise TypeError("calibration observer context requires an annotation")
    if hints.get(target.name) is not CalibrationTargetRef:
        raise TypeError("calibration observer target must be CalibrationTargetRef")
    return_hint = hints.get("return")
    generic = cast(
        "dict[str, object] | None",
        getattr(return_hint, "__pydantic_generic_metadata__", None),
    )
    if generic is None or (
        generic.get("origin") is not CalibrationObservation
        or generic.get("args") != (input_type,)
    ):
        raise TypeError(
            "calibration observer return annotation must match "
            "CalibrationObservation[input model]"
        )


def _validate_intent_builder(
    builder: Callable[..., object],
    *,
    input_type: type[BaseModel],
    intent_type: type[BaseModel],
) -> None:
    parameters, hints = _validate_function(
        builder,
        label="calibration intent builder",
    )
    if len(parameters) != 4:
        raise TypeError(
            "calibration intent builder requires exactly "
            "(context, target, inputs, dependencies)"
        )
    context, target, inputs, dependencies = parameters
    if context.name not in hints:
        raise TypeError("calibration intent builder context requires an annotation")
    if hints.get(target.name) is not CalibrationTargetRef:
        raise TypeError(
            "calibration intent builder target must be CalibrationTargetRef"
        )
    if hints.get(inputs.name) is not input_type:
        raise TypeError(
            "calibration intent builder inputs annotation must match its input model"
        )
    if hints.get(dependencies.name) != tuple[CalibrationDependencyEvidence, ...]:
        raise TypeError(
            "calibration intent builder dependencies annotation must be "
            "tuple[CalibrationDependencyEvidence, ...]"
        )
    if hints.get("return") is not intent_type:
        raise TypeError(
            "calibration intent builder return annotation must match the "
            "procedure intent model"
        )


def _validate_function(
    function: Callable[..., object],
    *,
    label: str,
) -> tuple[tuple[inspect.Parameter, ...], dict[str, object]]:
    if not inspect.isfunction(function):
        raise TypeError(f"{label} must be a Python function")
    if inspect.iscoroutinefunction(function):
        raise TypeError(f"{label} must be synchronous")
    parameters = tuple(inspect.signature(function).parameters.values())
    if any(
        parameter.kind
        not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        or cast("object", parameter.default) is not inspect.Parameter.empty
        for parameter in parameters
    ):
        raise TypeError(f"{label} requires positional parameters without defaults")
    try:
        hints = get_type_hints(function)
    except (NameError, TypeError) as error:
        raise TypeError(f"{label} annotations must be resolvable") from error
    return parameters, hints


def _calibration_definition_fingerprint(
    *,
    id: str,
    version: str,
    input_type: type[BaseModel],
    procedure: RegisteredProcedure,
    fanout_scope: str,
    max_in_flight: int,
    selector: Callable[..., object],
    observer: Callable[..., object],
    builder: Callable[..., object],
) -> Sha256ContentHash:
    identity = {
        "codec": _CALIBRATION_DEFINITION_FINGERPRINT_CODEC,
        "id": id,
        "version": version,
        "inputs": {
            "module": input_type.__module__,
            "qualname": input_type.__qualname__,
            "schema": input_type.model_json_schema(mode="validation"),
        },
        "procedure": procedure.ref.model_dump(mode="json"),
        "fanout_scope": fanout_scope,
        "max_in_flight": max_in_flight,
        "selector": _function_identity(selector, label="calibration selector"),
        "observer": _function_identity(observer, label="calibration observer"),
        "builder": _function_identity(builder, label="calibration intent builder"),
    }
    return f"sha256:{stable_content_hash(identity)}"


def _function_identity(
    function: Callable[..., object],
    *,
    label: str,
) -> dict[str, str]:
    try:
        source = dedent(inspect.getsource(function)).strip()
    except (OSError, TypeError) as error:
        raise TypeError(f"{label} source must be available to fingerprint") from error
    if not source:
        raise TypeError(f"{label} source must be non-empty")
    return {
        "module": function.__module__,
        "qualname": function.__qualname__,
        "source": source,
    }


def _require_non_blank(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


__all__ = [
    "MAX_CALIBRATION_REGISTRY_SIZE",
    "CalibrationDefinition",
    "CalibrationDependencyRequirement",
    "CalibrationObservation",
    "CalibrationRegistry",
    "RegisteredCalibration",
    "calibration",
]
