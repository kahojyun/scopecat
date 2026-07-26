# pyright: reportPrivateUsage=false
"""Closed quantum programs and core domain integration."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from scopecat.authoring import (
    ComputeInput,
    DomainExecution,
    DomainProgramDef,
    ExperimentModule,
    FloatType,
    IntType,
    ModuleBuilder,
    ModuleInvocation,
    ProductOutputs,
    ProductRef,
    ScalarType,
    ValueRef,
    ValueType,
    shot_axis,
)
from scopecat.authoring import (
    domain_execution as _core_domain_execution,
)
from scopecat.authoring import (
    domain_program as _core_domain_program,
)
from scopecat.authoring import input as core_input

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
    _SHOTS_INPUT_ID,
    QUANTUM_PROGRAM_DIALECT_ID,
    QUANTUM_PROGRAM_DIALECT_VERSION,
    ProgramFunction,
    ProgramInput,
    ProgramPort,
    ProgramResult,
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
    module_invocation: ModuleInvocation
    results: ProductOutputs
    arguments: tuple[tuple[str, ComputeInput], ...]
    compiler_arguments: tuple[tuple[str, ValueRef], ...]
    shots: ComputeInput

    def with_shots(self, shots: ComputeInput, /) -> QuantumProgramCall:
        """Return the same program call with a different acquisition count."""

        return _program_call(
            self.program,
            self.module_invocation.instance_id,
            module=self.module_invocation.module,
            inputs=dict(self.arguments),
            compiler_inputs=dict(self.compiler_arguments),
            shots=shots,
        )

    def with_compiler_inputs(self, **inputs: ValueRef) -> QuantumProgramCall:
        """Bind typed lowering-only values without changing the Program ABI."""

        compiler_inputs = dict(inputs)
        return _program_call(
            self.program,
            self.module_invocation.instance_id,
            module=_program_call_module(
                self.program,
                compiler_input_types={
                    name: value.value_type for name, value in compiler_inputs.items()
                },
            ),
            inputs=dict(self.arguments),
            compiler_inputs=compiler_inputs,
            shots=self.shots,
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

    __slots__ = ("_call_module", "_contract", "_definition")

    _call_module: ExperimentModule[...]
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
        self._call_module = _program_call_module(self)

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
            module=self._call_module,
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
            module=self._call_module,
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


def _domain_execution(
    program: DomainProgramDef,
    *,
    id: str | None = None,
    inputs: Mapping[ProgramPort, ComputeInput] | None = None,
    compiler_inputs: Mapping[str, ComputeInput] | None = None,
    results: Mapping[ProgramResult, ProductRef] | None = None,
) -> DomainExecution:
    """Bind one template's quantum program to core values and products."""

    if (
        program.dialect_id != QUANTUM_PROGRAM_DIALECT_ID
        or program.dialect_version != QUANTUM_PROGRAM_DIALECT_VERSION
        or not isinstance(program.body, Program)
    ):
        msg = "quantum domain execution requires a quantum program"
        raise TypeError(msg)
    declaration = program.body
    expected_program = _domain_program(
        declaration,
        compiler_inputs={
            port.id: port.value_type for port in program.compiler_input_ports
        },
    )
    if (
        program.id != expected_program.id
        or program.input_ports != expected_program.input_ports
        or program.compiler_input_ports != expected_program.compiler_input_ports
        or program.result_ports != expected_program.result_ports
    ):
        msg = "quantum program domain ports do not match its Program body"
        raise ValueError(msg)
    selected_inputs: Mapping[ProgramPort, ComputeInput] = (
        {} if inputs is None else inputs
    )
    selected_results: Mapping[ProgramResult, ProductRef] = (
        {} if results is None else results
    )
    selected_compiler_inputs: Mapping[str, ComputeInput] = (
        {} if compiler_inputs is None else compiler_inputs
    )
    if set(selected_inputs) != set(declaration.ports):
        msg = "quantum domain execution inputs must bind every declared port"
        raise ValueError(msg)
    if set(selected_results) != set(declaration.results):
        msg = "quantum domain execution results must bind every declared result"
        raise ValueError(msg)
    if set(selected_compiler_inputs) != {
        port.id for port in program.compiler_input_ports
    }:
        msg = "quantum compiler inputs must bind every declared port"
        raise ValueError(msg)
    normalized_inputs = {
        handle.id: (
            float(value)
            if isinstance(handle, ProgramInput)
            and isinstance(handle.value_type.atom, FloatType)
            and isinstance(value, int)
            and not isinstance(value, bool)
            else value
        )
        for handle, value in selected_inputs.items()
    }
    return _core_domain_execution(
        program,
        id=id,
        inputs=normalized_inputs,
        compiler_inputs=selected_compiler_inputs,
        results={handle.id: value for handle, value in selected_results.items()},
    )


def _program_call_module(
    program: Program,
    *,
    compiler_input_types: Mapping[str, ValueType] | None = None,
) -> ExperimentModule[...]:
    """Build the reusable core module owned by one program definition."""

    selected_compiler_input_types = compiler_input_types or {}
    domain = _domain_program(
        program,
        compiler_inputs=selected_compiler_input_types,
    )
    local_inputs = {
        port.id: core_input(port.id, port.value_type) for port in domain.input_ports
    }
    local_compiler_inputs = {
        port.id: core_input(port.id, port.value_type)
        for port in domain.compiler_input_ports
    }
    shots_input = core_input(
        _SHOTS_INPUT_ID,
        ScalarType(IntType(minimum=1)),
    )
    builder = ModuleBuilder(id=f"{program.id}.call").inputs(
        *local_inputs.values(),
        *local_compiler_inputs.values(),
        shots_input,
    )
    for result in program.results:
        contract = result.contract
        builder = builder.product(
            result.id,
            unit=contract.unit,
            dtype=contract.dtype,
            axes=(shot_axis(shots_input),),
        )
    execution = _domain_execution(
        domain,
        inputs={port: local_inputs[port.id] for port in program.ports},
        compiler_inputs=local_compiler_inputs,
        results={result: builder.products[result.id] for result in program.results},
    )
    return builder.domain(execution).build()


def _program_call(
    program: Program,
    instance_id: str,
    /,
    *,
    module: ExperimentModule[...],
    inputs: Mapping[str, ComputeInput],
    compiler_inputs: Mapping[str, ValueRef],
    shots: ComputeInput,
) -> QuantumProgramCall:
    """Instantiate one use of a definition's cached core module."""

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

    invocation = module.instantiate(
        instance_id,
        {
            **inputs,
            **compiler_inputs,
            _SHOTS_INPUT_ID: shots,
        },
    )
    return QuantumProgramCall(
        program=program,
        module_invocation=invocation,
        results=ProductOutputs(
            {result.id: invocation.products[result.id] for result in program.results}
        ),
        arguments=tuple(inputs.items()),
        compiler_arguments=tuple(compiler_inputs.items()),
        shots=shots,
    )
