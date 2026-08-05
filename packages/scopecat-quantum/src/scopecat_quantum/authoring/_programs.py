# pyright: reportPrivateUsage=false
"""Closed quantum programs and core domain integration."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from scopecat.authoring import (
    ComputeInput,
    IntType,
    ScalarType,
    ValueRef,
    ValueType,
)
from scopecat.domain.program import DomainProgramDef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.kernel.value_validation import coerce_literal
from scopecat.program.domain import (
    DomainCall,
    create_domain_call_internal,
)
from scopecat.program.domain import (
    domain_program as _core_domain_program,
)
from scopecat.program.identities import DomainCallKey
from scopecat.program.products import (
    ModuleProductDecl,
    ProductRefs,
    ProductValueSpec,
    shot_axis,
)

from scopecat_quantum._ids import (
    QuantumProgramId,
)

from ._analysis import (
    _summarize_fragment,
    program_port_type,
)
from ._inspection import (
    describe,
    draw,
)
from ._ir import (
    QUANTUM_PROGRAM_DIALECT_ID,
    QUANTUM_PROGRAM_DIALECT_VERSION,
    ProgramFunction,
    ProgramInput,
    ProgramPort,
    ProgramResults,
    PulseElement,
    QuantumFragment,
)


class _ProgramFunctionContract(Protocol):
    @property
    def signature(self) -> inspect.Signature: ...


@dataclass(frozen=True, slots=True, repr=False)
class QuantumProgramCall:
    """One program invocation with automatically owned result products."""

    program: Program
    domain_call: DomainCall
    arguments: tuple[tuple[str, ComputeInput], ...]
    compiler_arguments: tuple[tuple[str, ValueRef], ...]
    shots: ComputeInput

    @property
    def results(self) -> ProductRefs:
        """Return products owned by this native domain occurrence."""

        return self.domain_call.results

    def with_shots(self, shots: ComputeInput, /) -> QuantumProgramCall:
        """Return the same program call with a different acquisition count."""

        return _program_call(
            self.program,
            self.domain_call.id,
            inputs=dict(self.arguments),
            compiler_inputs=dict(self.compiler_arguments),
            shots=shots,
            key=self.domain_call.key,
        )

    def with_compiler_inputs(self, **inputs: ValueRef) -> QuantumProgramCall:
        """Bind typed lowering-only values without changing the Program ABI."""

        compiler_inputs = dict(inputs)
        return _program_call(
            self.program,
            self.domain_call.id,
            inputs=dict(self.arguments),
            compiler_inputs=compiler_inputs,
            shots=self.shots,
            key=self.domain_call.key,
        )


@dataclass(frozen=True, slots=True, repr=False)
class Program:
    """A closed symbolic program containing logical and physical statements."""

    ir_id: QuantumProgramId
    body: QuantumFragment
    elements: tuple[PulseElement, ...]
    inputs: tuple[ProgramInput, ...]
    results: ProgramResults
    description: str | None = None

    @property
    def id(self) -> str:
        """Return the stable program identity."""

        return self.ir_id.value

    @property
    def ports(self) -> tuple[ProgramPort, ...]:
        """Return bindable logical elements followed by scalar inputs."""

        return (*self.elements, *self.inputs)

    def describe(self) -> str:
        """Describe the program's typed ports and result contracts as text."""

        return describe(self)

    def draw(self) -> str:
        """Draw the program's recursive source structure as a text tree."""

        return draw(self)


class ProgramDefinition(Program):
    """A function-authored program with an inspectable call signature."""

    __slots__ = ("_contract", "_definition")

    _contract: _ProgramFunctionContract
    _definition: ProgramFunction

    def __init__(
        self,
        declaration: Program,
        definition: ProgramFunction,
        contract: _ProgramFunctionContract,
    ) -> None:
        super().__init__(
            ir_id=declaration.ir_id,
            body=declaration.body,
            elements=declaration.elements,
            inputs=declaration.inputs,
            results=declaration.results,
            description=declaration.description,
        )
        self._definition = definition
        self._contract = contract

    @property
    def __wrapped__(self) -> ProgramFunction:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._contract.signature.replace(
            parameters=tuple(
                parameter.replace(annotation=ComputeInput)
                for parameter in self._contract.signature.parameters.values()
            ),
            return_annotation=QuantumProgramCall,
        )

    def __call__(
        self,
        *args: ComputeInput,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Bind ports in their declared Python order."""

        bound = self._contract.signature.bind(*args, **inputs)
        return _program_call(
            self,
            self.id.rsplit(".", maxsplit=1)[-1],
            inputs=cast("Mapping[str, ComputeInput]", bound.arguments),
            compiler_inputs={},
            shots=1,
        )

    def call(
        self,
        instance_id: str,
        /,
        *args: ComputeInput,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Bind an explicitly named call in declared port order."""

        bound = self._contract.signature.bind(*args, **inputs)
        return _program_call(
            self,
            instance_id,
            inputs=cast("Mapping[str, ComputeInput]", bound.arguments),
            compiler_inputs={},
            shots=1,
        )


def _domain_program(
    declaration: Program,
    *,
    compiler_inputs: Mapping[str, ValueType] | None = None,
) -> DomainProgramDef:
    """Project a unified declaration into core's domain program seam."""

    repeat_input_ids = {
        input_handle.id
        for input_handle in _summarize_fragment(declaration.body).repeat_inputs
    }
    return _core_domain_program(
        declaration.id,
        dialect_id=QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=QUANTUM_PROGRAM_DIALECT_VERSION,
        body=declaration,
        inputs={
            port.id: program_port_type(
                port,
                non_negative=port.id in repeat_input_ids,
            )
            for port in declaration.ports
        },
        compiler_inputs=compiler_inputs,
        results={result.id: result for result in declaration.results},
    )


def _program_call(
    program: Program,
    instance_id: str,
    /,
    *,
    inputs: Mapping[str, ComputeInput],
    compiler_inputs: Mapping[str, ValueRef],
    shots: ComputeInput,
    key: DomainCallKey | None = None,
) -> QuantumProgramCall:
    """Create one native domain occurrence from a closed program definition."""

    expected = {port.id for port in program.ports}
    supplied = set(inputs)
    missing = sorted(expected - supplied)
    unknown = sorted(supplied - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(repr(item) for item in missing))
        if unknown:
            details.append("unknown " + ", ".join(repr(item) for item in unknown))
        raise ValueError("invalid quantum program call inputs: " + "; ".join(details))

    domain = _domain_program(
        program,
        compiler_inputs={
            name: value.value_type for name, value in compiler_inputs.items()
        },
    )
    normalized_shots = _normalize_shots(shots)
    call = create_domain_call_internal(
        domain,
        id=instance_id,
        inputs={
            port.id: _normalize_program_input(port, inputs[port.id])
            for port in program.ports
        },
        compiler_inputs=compiler_inputs,
        result_products={
            result.id: ModuleProductDecl(
                id=result.id,
                value_spec=ProductValueSpec(
                    unit=result.contract.unit,
                    dtype=result.contract.dtype,
                    axes=(
                        shot_axis(
                            cast("ValueRef | Quantity | float", normalized_shots),
                            shared_as="shot",
                        ),
                    ),
                ),
            )
            for result in program.results
        },
        key=key,
    )
    return QuantumProgramCall(
        program=program,
        domain_call=call,
        arguments=tuple(inputs.items()),
        compiler_arguments=tuple(compiler_inputs.items()),
        shots=shots,
    )


def _normalize_program_input(
    port: ProgramPort,
    value: ComputeInput,
) -> ComputeInput:
    value_type = program_port_type(port)
    if isinstance(value, ValueRef):
        require_assignable(
            value.value_type,
            value_type,
            path=("inputs", port.id),
        )
        return value
    normalized = coerce_literal(
        value_type,
        value,
        path=("inputs", port.id),
    )
    return cast("ComputeInput", normalized)


def _normalize_shots(shots: ComputeInput) -> ComputeInput:
    value_type = ScalarType(IntType(minimum=1))
    if isinstance(shots, ValueRef):
        require_assignable(shots.value_type, value_type, path=("shots",))
        return shots
    return cast(
        "ComputeInput",
        coerce_literal(value_type, shots, path=("shots",)),
    )
