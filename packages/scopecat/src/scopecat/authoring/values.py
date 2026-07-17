"""First-class typed values for the public module-composition DSL."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from inspect import Parameter, signature
from typing import cast
from uuid import UUID, uuid4

from scopecat.authoring._frozen_values import freeze_runtime_input
from scopecat.authoring._parameter_contracts import (
    ParameterLookupContract,
    ParameterValueContract,
    merge_parameter_contracts,
)
from scopecat.authoring._value_refs import (
    TableRow,
    ValueRef,
    internal_input_value_ref,
    internal_lower_scalar_value_ref,
    internal_operation_result_value_ref,
    internal_point_value_ref,
    internal_value_ref_from_expression,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)
from scopecat.compiler.relations.model import (
    param,
    parameter_series,
    table,
)
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.routes import ResolvedRoute
from scopecat.kernel.value_type_compatibility import literal_scalar_type
from scopecat.kernel.value_types import Route, Scalar, Series, ValueType
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type ComputeFunction = Callable[..., object]
type ScalarInput = Quantity | EntityRef | PayloadValue | str | int | float | bool | None
type ComputeInput = ValueRef | RouteRef | ScalarInput
type RuntimeInput = (
    Quantity
    | EntityRef
    | str
    | int
    | float
    | bool
    | None
    | list[RuntimeInput]
    | tuple[RuntimeInput, ...]
    | Mapping[str, RuntimeInput]
)
type MetadataValue = JsonValue
type ModuleInput = (
    ValueRef
    | ScalarInput
    | list[ModuleInput]
    | tuple[ModuleInput, ...]
    | Mapping[str, ModuleInput]
)
type ParameterKeyInput = (
    ValueRef | Quantity | EntityRef | str | int | float | bool | None
)


@dataclass(frozen=True, slots=True)
class ComputeDeclarationKey:
    """Nominal identity shared by a compute declaration and its result use."""

    value: UUID

    @classmethod
    def fresh(cls) -> ComputeDeclarationKey:
        return cls(uuid4())


@dataclass(frozen=True, slots=True, repr=False)
class RouteRef:
    """Explicit typed route edge for a point-local compute input."""

    port_id: LogicalResourcePortId
    value_type: Route


@dataclass(frozen=True, slots=True, repr=False)
class Compute:
    """A typed compute declaration and its composable output value."""

    id: str
    fn: ComputeFunction
    inputs: tuple[tuple[str, ComputeInput], ...]
    output_type: ValueType
    declaration_key: ComputeDeclarationKey

    def __post_init__(self) -> None:
        if not self.id:
            msg = "compute id must be non-empty"
            raise ValueError(msg)
        input_names = tuple(name for name, _value in self.inputs)
        if any(not name for name in input_names):
            msg = "compute input names must be non-empty"
            raise ValueError(msg)
        if len(set(input_names)) != len(input_names):
            msg = f"compute {self.id!r} has duplicate input names"
            raise ValueError(msg)
        invalid = [name for name, value in self.inputs if not _is_compute_input(value)]
        if invalid:
            msg = (
                f"compute {self.id!r} inputs must be typed values, routes, or "
                f"scalar literals; invalid inputs: {', '.join(invalid)}"
            )
            raise TypeError(msg)
        _validate_compute_function(self.id, self.fn, input_names)

    @property
    def output(self) -> ValueRef:
        return internal_operation_result_value_ref(
            self.id,
            self.output_type,
            origin=(self.declaration_key,),
            point_dependencies=tuple(
                dependency
                for _name, value in self.inputs
                if isinstance(value, ValueRef)
                for dependency in internal_value_ref_point_dependencies(value)
            ),
        )


def input(  # noqa: A001
    id: str,  # noqa: A002
    value_type: ValueType,
) -> ValueRef:
    """Declare one typed module input value.

    Register the returned value with :meth:`ModuleBuilder.inputs`, then pass the
    same object to compute inputs, child modules, routes, records, or bindings.
    """

    return internal_input_value_ref(id, value_type)


def point(id: str, value_type: Scalar) -> ValueRef:  # noqa: A002
    """Declare a typed scalar supplied by the current experiment point.

    Pass the same value to module bindings and scan factories. This keeps the
    coordinate identity and its semantic type on one first-class value edge.
    """

    return internal_point_value_ref(id, value_type)


def parameter(id: str, value_type: ValueType) -> ValueRef:  # noqa: A002
    """Declare a typed scalar, series, or table parameter dependency."""

    return internal_value_ref_from_expression(
        (
            param(id)
            if isinstance(value_type, Scalar)
            else parameter_series(id)
            if isinstance(value_type, Series)
            else table(id)
        ),
        value_type,
        parameter_contracts=(
            ParameterValueContract(
                parameter_id=id,
                value_type=value_type,
            ),
        ),
    )


def parameter_lookup(
    table_id: str,
    *,
    key: Mapping[str, ParameterKeyInput],
    column: str,
    value_type: Scalar,
) -> ValueRef:
    """Declare one typed parameter-table lookup dependency."""

    if any(
        not isinstance(name, str) or not name or not _is_parameter_key_input(value)
        for name, value in cast("Mapping[object, object]", key).items()
    ):
        msg = "parameter lookup keys require typed scalar values or scalar literals"
        raise TypeError(msg)

    captured_key = {
        name: value
        if isinstance(value, ValueRef)
        else cast("ParameterKeyInput", freeze_runtime_input(value))
        for name, value in key.items()
    }
    expression_key = {
        name: internal_lower_scalar_value_ref(value)
        if isinstance(value, ValueRef)
        else value
        for name, value in captured_key.items()
    }
    return internal_value_ref_from_expression(
        param(table_id, key=expression_key, column=column),
        value_type,
        parameter_contracts=merge_parameter_contracts(
            (
                ParameterLookupContract(
                    parameter_id=table_id,
                    key_columns=tuple(captured_key),
                    key_types=tuple(
                        (name, _parameter_key_value_type(value))
                        for name, value in captured_key.items()
                    ),
                    literal_key_columns=frozenset(
                        name
                        for name, value in captured_key.items()
                        if not isinstance(value, ValueRef)
                    ),
                    column_id=column,
                    value_type=value_type,
                ),
            ),
            *(
                internal_value_ref_parameter_contracts(value)
                for value in captured_key.values()
                if isinstance(value, ValueRef)
            ),
        ),
        point_dependencies=tuple(
            dependency
            for value in captured_key.values()
            if isinstance(value, ValueRef)
            for dependency in internal_value_ref_point_dependencies(value)
        ),
    )


def route(
    port_id: str,
    *,
    capabilities: tuple[str, ...] = (),
) -> RouteRef:
    """Declare one explicit point-local route dependency."""

    if any(not capability for capability in capabilities):
        msg = "route capabilities must be a sequence of non-empty strings"
        raise ValueError(msg)
    return RouteRef(
        port_id=logical_resource_port_id(port_id),
        value_type=Route(capabilities=capabilities),
    )


def compute(
    id: str,  # noqa: A002
    *,
    fn: ComputeFunction,
    inputs: Mapping[str, ComputeInput] | None = None,
    output_type: ValueType,
) -> Compute:
    """Declare a compute node whose output is a first-class typed value."""

    selected_inputs = tuple((inputs or {}).items())
    invalid = [name for name, value in selected_inputs if not _is_compute_input(value)]
    if invalid:
        msg = (
            f"compute {id!r} inputs must be typed values, routes, or "
            f"scalar literals; invalid inputs: {', '.join(invalid)}"
        )
        raise TypeError(msg)
    return Compute(
        id=id,
        fn=fn,
        inputs=tuple(
            (name, _capture_compute_input(value)) for name, value in selected_inputs
        ),
        output_type=output_type,
        declaration_key=ComputeDeclarationKey.fresh(),
    )


def _capture_compute_input(value: ComputeInput) -> ComputeInput:
    if isinstance(value, ValueRef | RouteRef):
        return value
    if isinstance(value, PayloadValue):
        return value
    return cast("ComputeInput", freeze_runtime_input(value))


def _is_compute_input(value: object) -> bool:
    return value is None or isinstance(
        value,
        ValueRef
        | RouteRef
        | Quantity
        | EntityRef
        | PayloadValue
        | str
        | int
        | float
        | bool,
    )


def _is_parameter_key_input(value: object) -> bool:
    return (
        value is None
        or isinstance(value, Quantity | EntityRef | str | int | float | bool)
        or (isinstance(value, ValueRef) and isinstance(value.value_type, Scalar))
    )


def _parameter_key_value_type(value: ParameterKeyInput) -> Scalar:
    if isinstance(value, ValueRef):
        return cast("Scalar", value.value_type)
    return literal_scalar_type(value)


def module_input_is_valid(value: object) -> bool:
    """Return whether a module edge is typed or a closed literal value."""

    return _nested_input_is_valid(
        value,
        allow_value_ref=True,
        allow_payload=True,
        seen=set(),
    )


def runtime_input_is_valid(value: object) -> bool:
    """Return whether a user input belongs to the closed runtime value domain."""

    return _nested_input_is_valid(
        value,
        allow_value_ref=False,
        allow_payload=False,
        seen=set(),
    )


def _nested_input_is_valid(
    value: object,
    *,
    allow_value_ref: bool,
    allow_payload: bool,
    seen: set[int],
) -> bool:
    if value is None or isinstance(value, str | int | bool):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Quantity):
        return math.isfinite(value.value)
    if isinstance(value, EntityRef):
        return _nested_input_is_valid(
            value.metadata,
            allow_value_ref=False,
            allow_payload=False,
            seen=seen,
        )
    if isinstance(value, PayloadValue):
        return allow_payload
    if isinstance(value, ValueRef):
        return allow_value_ref
    marker = id(value)
    if marker in seen:
        return False
    if isinstance(value, Mapping):
        selected = cast("Mapping[object, object]", value)
        seen.add(marker)
        valid = all(
            isinstance(name, str)
            and _nested_input_is_valid(
                item,
                allow_value_ref=allow_value_ref,
                allow_payload=allow_payload,
                seen=seen,
            )
            for name, item in selected.items()
        )
        seen.remove(marker)
        return valid
    if isinstance(value, list | tuple):
        selected = cast("list[object] | tuple[object, ...]", value)
        seen.add(marker)
        valid = all(
            _nested_input_is_valid(
                item,
                allow_value_ref=allow_value_ref,
                allow_payload=allow_payload,
                seen=seen,
            )
            for item in selected
        )
        seen.remove(marker)
        return valid
    return False


def _validate_compute_function(
    compute_id: str,
    fn: ComputeFunction,
    input_names: tuple[str, ...],
) -> None:
    try:
        function_signature = signature(fn)
    except (TypeError, ValueError) as error:
        msg = f"compute {compute_id!r} function must have an inspectable signature"
        raise TypeError(msg) from error
    unsupported = [
        parameter.name
        for parameter in function_signature.parameters.values()
        if parameter.kind
        in {
            Parameter.POSITIONAL_ONLY,
            Parameter.VAR_POSITIONAL,
            Parameter.VAR_KEYWORD,
        }
    ]
    if unsupported:
        msg = (
            f"compute {compute_id!r} function must use explicit named parameters; "
            f"unsupported parameters: {', '.join(unsupported)}"
        )
        raise TypeError(msg)
    try:
        function_signature.bind(**dict.fromkeys(input_names, object()))
    except TypeError as error:
        msg = (
            f"compute {compute_id!r} function signature does not match declared "
            f"inputs {input_names}: {error}"
        )
        raise TypeError(msg) from error


__all__ = [
    "Compute",
    "ComputeInput",
    "MetadataValue",
    "ModuleInput",
    "ParameterKeyInput",
    "ResolvedRoute",
    "RouteRef",
    "RuntimeInput",
    "ScalarInput",
    "TableRow",
    "ValueRef",
    "compute",
    "input",
    "parameter",
    "parameter_lookup",
    "point",
    "route",
]
