"""Domain-program authoring and module-bound execution.

Domain bodies and result contracts are opaque transient values.  Core owns
only their stable identities, typed value ports, and logical product bindings;
an adapter for the selected dialect owns interpretation of the body.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from scopecat.authoring._intents import ComputeNodeInputValue
from scopecat.authoring._products import ProductRef
from scopecat.authoring._value_refs import ValueRef, capture_runtime_input
from scopecat.authoring.value_types import Scalar, ValueType
from scopecat.domain.program import (
    DomainInputPort,
    DomainProgramDef,
    DomainResultPort,
)
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductId


@dataclass(frozen=True, slots=True)
class DomainExecution:
    """One identified domain-program effect placed in a module effects."""

    id: str
    program: DomainProgramDef
    input_bindings: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    compiler_input_bindings: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    result_bindings: tuple[tuple[str, ProductRef], ...] = ()


@dataclass(frozen=True, slots=True)
class LoweredDomainExecution:
    """Internal product-resolved form of the module-owned execution."""

    id: str
    program: DomainProgramDef
    input_bindings: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    compiler_input_bindings: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    result_bindings: tuple[tuple[str, ProductId], ...] = ()


def lower_domain_execution(execution: DomainExecution) -> LoweredDomainExecution:
    """Lower a module call after its product ownership has been validated."""

    return LoweredDomainExecution(
        id=execution.id,
        program=execution.program,
        input_bindings=execution.input_bindings,
        compiler_input_bindings=execution.compiler_input_bindings,
        result_bindings=tuple(
            (result_id, product.product_id)
            for result_id, product in execution.result_bindings
        ),
    )


def domain_program(
    id: str,
    *,
    dialect_id: str,
    dialect_version: str,
    body: object,
    inputs: Mapping[str, Scalar] | None = None,
    compiler_inputs: Mapping[str, ValueType] | None = None,
    results: Mapping[str, object | None] | None = None,
) -> DomainProgramDef:
    """Declare an opaque program with ordered typed input and result ports."""

    selected_inputs = cast("Mapping[str, ValueType]", inputs or {})
    if any(
        not isinstance(value_type, Scalar) for value_type in selected_inputs.values()
    ):
        raise TypeError("domain program inputs must be scalar; use compiler_inputs")
    return DomainProgramDef(
        id=id,
        dialect_id=dialect_id,
        dialect_version=dialect_version,
        body=body,
        input_ports=tuple(
            DomainInputPort(port_id, value_type)
            for port_id, value_type in selected_inputs.items()
        ),
        compiler_input_ports=tuple(
            DomainInputPort(port_id, value_type)
            for port_id, value_type in (compiler_inputs or {}).items()
        ),
        result_ports=tuple(
            DomainResultPort(port_id, contract)
            for port_id, contract in (results or {}).items()
        ),
    )


def domain_execution(
    program: DomainProgramDef,
    *,
    id: str | None = None,
    inputs: Mapping[str, ComputeNodeInputValue] | None = None,
    compiler_inputs: Mapping[str, ComputeNodeInputValue] | None = None,
    results: Mapping[str, ProductRef] | None = None,
) -> DomainExecution:
    """Bind one module call to typed values and composed products."""

    execution_id = program.id if id is None else id
    if not execution_id:
        raise ValueError("domain execution id must be non-empty")
    selected_inputs = inputs or {}
    selected_compiler_inputs = compiler_inputs or {}
    selected_results = results or {}
    _require_exact_keys(
        "domain execution inputs",
        selected_inputs,
        tuple(port.id for port in program.input_ports),
    )
    _require_exact_keys(
        "domain execution compiler inputs",
        selected_compiler_inputs,
        tuple(port.id for port in program.compiler_input_ports),
    )
    _require_exact_keys(
        "domain execution results",
        selected_results,
        tuple(port.id for port in program.result_ports),
    )
    return DomainExecution(
        id=execution_id,
        program=program,
        input_bindings=tuple(
            (port.id, _capture_domain_input(selected_inputs[port.id]))
            for port in program.input_ports
        ),
        compiler_input_bindings=tuple(
            (port.id, _capture_domain_input(selected_compiler_inputs[port.id]))
            for port in program.compiler_input_ports
        ),
        result_bindings=tuple(
            (
                port.id,
                selected_results[port.id],
            )
            for port in program.result_ports
        ),
    )


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


def _capture_domain_input(value: ComputeNodeInputValue) -> ComputeNodeInputValue:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value
    return cast("ComputeNodeInputValue", capture_runtime_input(value))
