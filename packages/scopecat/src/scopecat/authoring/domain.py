"""Domain-neutral authored programs and compile-time calls.

Domain bodies and result contracts are opaque transient values.  Core owns
only their stable identities, typed value ports, and logical product bindings;
an adapter for the selected dialect owns interpretation of the body.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from scopecat.authoring._frozen_values import freeze_runtime_input
from scopecat.authoring._intents import ComputeNodeInputValue
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.value_types import Scalar, Series, Table, ValueType
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductId, product_id
from scopecat.kernel.symbols import SymbolId
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


@dataclass(frozen=True, slots=True)
class DomainInputPort:
    """One typed plan-stage input accepted by an authored domain program."""

    id: str
    value_type: ValueType

    def __post_init__(self) -> None:
        if not _is_non_empty_string(cast("object", self.id)):
            raise ValueError("domain input port ids must be non-empty")
        if not _is_value_type(cast("object", self.value_type)):
            raise TypeError("domain input ports require a core ValueType")


@dataclass(frozen=True, slots=True)
class DomainResultPort:
    """One named output whose contract is interpreted by the dialect."""

    id: str
    contract: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not _is_non_empty_string(cast("object", self.id)):
            raise ValueError("domain result port ids must be non-empty")


@dataclass(frozen=True, slots=True)
class DomainProgramDef:
    """Opaque domain program declaration retained through target linking."""

    id: str
    dialect_id: str
    dialect_version: str
    body: object = field(repr=False)
    input_ports: tuple[DomainInputPort, ...] = ()
    result_ports: tuple[DomainResultPort, ...] = ()
    scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            _is_non_empty_string(cast("object", value))
            for value in (self.id, self.dialect_id, self.dialect_version)
        ):
            raise ValueError(
                "domain program, dialect, and dialect version ids must be non-empty"
            )
        if not _is_tuple_of(
            cast("object", self.input_ports),
            DomainInputPort,
        ):
            raise TypeError("domain program input_ports must contain DomainInputPort")
        if not _is_tuple_of(
            cast("object", self.result_ports),
            DomainResultPort,
        ):
            raise TypeError("domain program result_ports must contain DomainResultPort")
        if not _is_string_tuple(cast("object", self.scope)):
            raise TypeError("domain program scope must contain non-empty strings")
        _require_unique("domain input port", tuple(p.id for p in self.input_ports))
        _require_unique("domain result port", tuple(p.id for p in self.result_ports))

    @property
    def symbol_id(self) -> SymbolId:
        return SymbolId(scope=self.scope, local_id=self.id)

    def __deepcopy__(self, _memo: dict[int, object]) -> DomainProgramDef:
        # The body is trusted frozen transient IR owned by its dialect.
        return self


@dataclass(frozen=True, slots=True)
class DomainCall:
    """One authored invocation binding values and logical product outputs."""

    id: str
    program: DomainProgramDef
    input_bindings: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    result_bindings: tuple[tuple[str, ProductId], ...] = ()
    scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _is_non_empty_string(cast("object", self.id)):
            raise ValueError("domain call ids must be non-empty")
        if not isinstance(cast("object", self.program), DomainProgramDef):
            raise TypeError("domain calls require a DomainProgramDef")
        if not _valid_input_bindings(cast("object", self.input_bindings)):
            raise TypeError(
                "domain call input_bindings require named authored scalar values"
            )
        if not _valid_result_bindings(cast("object", self.result_bindings)):
            raise TypeError(
                "domain call result_bindings require named local ProductId values"
            )
        if not _is_string_tuple(cast("object", self.scope)):
            raise TypeError("domain call scope must contain non-empty strings")
        _require_unique("domain call input", tuple(k for k, _ in self.input_bindings))
        _require_unique("domain call result", tuple(k for k, _ in self.result_bindings))
        expected_inputs = tuple(port.id for port in self.program.input_ports)
        actual_inputs = tuple(name for name, _value in self.input_bindings)
        if actual_inputs != expected_inputs:
            raise ValueError(
                "domain call input bindings must match program port declaration order"
            )
        expected_results = tuple(port.id for port in self.program.result_ports)
        actual_results = tuple(name for name, _value in self.result_bindings)
        if actual_results != expected_results:
            raise ValueError(
                "domain call result bindings must match program port declaration order"
            )
        object.__setattr__(
            self,
            "input_bindings",
            tuple(
                (name, _capture_domain_input(value))
                for name, value in self.input_bindings
            ),
        )

    @property
    def symbol_id(self) -> SymbolId:
        return SymbolId(scope=self.scope, local_id=self.id)


def domain_program(
    id: str,  # noqa: A002
    *,
    dialect_id: str,
    dialect_version: str,
    body: object,
    inputs: Mapping[str, ValueType] | None = None,
    results: Mapping[str, object | None] | None = None,
) -> DomainProgramDef:
    """Declare an opaque program with ordered typed input and result ports."""

    if inputs is not None and not isinstance(cast("object", inputs), Mapping):
        raise TypeError("domain program inputs must be a mapping")
    if results is not None and not isinstance(cast("object", results), Mapping):
        raise TypeError("domain program results must be a mapping")
    return DomainProgramDef(
        id=id,
        dialect_id=dialect_id,
        dialect_version=dialect_version,
        body=body,
        input_ports=tuple(
            DomainInputPort(port_id, value_type)
            for port_id, value_type in (inputs or {}).items()
        ),
        result_ports=tuple(
            DomainResultPort(port_id, contract)
            for port_id, contract in (results or {}).items()
        ),
    )


def domain_call(
    id: str,  # noqa: A002
    program: DomainProgramDef,
    *,
    inputs: Mapping[str, ComputeNodeInputValue] | None = None,
    results: Mapping[str, str] | None = None,
) -> DomainCall:
    """Bind one program invocation to authored values and module products."""

    if not isinstance(cast("object", program), DomainProgramDef):
        raise TypeError("domain_call program must be a DomainProgramDef")
    if inputs is not None and not isinstance(cast("object", inputs), Mapping):
        raise TypeError("domain call inputs must be a mapping")
    if results is not None and not isinstance(cast("object", results), Mapping):
        raise TypeError("domain call results must be a mapping")
    selected_inputs = inputs or {}
    selected_results = results or {}
    if any(not _is_domain_input_value(value) for value in selected_inputs.values()):
        raise TypeError("domain call inputs contain an unsupported authored value")
    if any(
        not _is_non_empty_string(cast("object", value))
        for value in selected_results.values()
    ):
        raise TypeError("domain call results must name non-empty local products")
    _require_exact_keys(
        "domain call inputs",
        selected_inputs,
        tuple(port.id for port in program.input_ports),
    )
    _require_exact_keys(
        "domain call results",
        selected_results,
        tuple(port.id for port in program.result_ports),
    )
    return DomainCall(
        id=id,
        program=program,
        input_bindings=tuple(
            (port.id, selected_inputs[port.id]) for port in program.input_ports
        ),
        result_bindings=tuple(
            (
                port.id,
                product_id(selected_results[port.id]),
            )
            for port in program.result_ports
        ),
    )


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} ids must be unique")


def _require_exact_keys(
    label: str,
    values: Mapping[str, object],
    expected: tuple[str, ...],
) -> None:
    unknown = sorted(set(values) - set(expected))
    missing = sorted(set(expected) - set(values))
    if unknown or missing:
        details: list[str] = []
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        if missing:
            details.append("missing: " + ", ".join(missing))
        raise ValueError(f"{label} must match declared ports ({'; '.join(details)})")


def _is_domain_input_value(value: object) -> bool:
    return value is None or isinstance(
        value,
        ValueRef | Quantity | EntityRef | PayloadValue | str | int | float | bool,
    )


def _capture_domain_input(value: ComputeNodeInputValue) -> ComputeNodeInputValue:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value.model_copy()
    return cast("ComputeNodeInputValue", freeze_runtime_input(value))


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_value_type(value: object) -> bool:
    return isinstance(value, Scalar | Series | Table)


def _is_tuple_of(value: object, item_type: type[object]) -> bool:
    if not isinstance(value, tuple):
        return False
    return all(
        isinstance(item, item_type) for item in cast("tuple[object, ...]", value)
    )


def _is_string_tuple(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    return all(_is_non_empty_string(item) for item in cast("tuple[object, ...]", value))


def _valid_input_bindings(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    for binding in cast("tuple[object, ...]", value):
        if not isinstance(binding, tuple):
            return False
        selected = cast("tuple[object, ...]", binding)
        if len(selected) != 2:
            return False
        name, input_value = selected
        if not _is_non_empty_string(name) or not _is_domain_input_value(input_value):
            return False
    return True


def _valid_result_bindings(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    for binding in cast("tuple[object, ...]", value):
        if not isinstance(binding, tuple):
            return False
        selected = cast("tuple[object, ...]", binding)
        if len(selected) != 2:
            return False
        name, product = selected
        if not _is_non_empty_string(name) or not isinstance(product, ProductId):
            return False
    return True


__all__ = [
    "DomainCall",
    "DomainInputPort",
    "DomainProgramDef",
    "DomainResultPort",
    "domain_call",
    "domain_program",
]
