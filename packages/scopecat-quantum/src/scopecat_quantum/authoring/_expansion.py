# pyright: reportPrivateUsage=false
"""Expansion and validation of authored fragment calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from scopecat.authoring.value_types import ValueValidationError, coerce_literal

from ._analysis import (
    _program_input_type,
    _summarize_fragment,
)
from ._ir import (
    Coupler,
    ProgramBindingError,
    ProgramInput,
    QuantumFragment,
    Qubit,
    _ExpandedFragment,
    _FragmentCall,
    _FragmentHandle,
    _QuantumConditionalFragment,
    _QuantumParallelFragment,
    _QuantumRepeatFragment,
    _QuantumSequenceFragment,
)


def _expand_fragment_calls(
    value: QuantumFragment,
    bindings: Mapping[str, object],
    *,
    stack: tuple[_FragmentHandle, ...] = (),
) -> QuantumFragment:
    if isinstance(value, _FragmentCall):
        definition = value.definition
        if any(definition is active for active in stack):
            chain = " -> ".join((*tuple(item.id for item in stack), definition.id))
            raise ProgramBindingError(f"quantum fragment expansion cycle: {chain}")
        body = _evaluate_fragment_call(value, bindings)
        expanded = _expand_fragment_calls(
            body,
            bindings,
            stack=(*stack, definition),
        )
        _validate_expanded_fragment(value, expanded)
        return _ExpandedFragment(definition_id=definition.id, body=expanded)
    if isinstance(value, _ExpandedFragment):
        return replace(
            value,
            body=_expand_fragment_calls(value.body, bindings, stack=stack),
        )
    if isinstance(value, _QuantumSequenceFragment):
        return replace(
            value,
            operations=tuple(
                _expand_fragment_calls(operation, bindings, stack=stack)
                for operation in value.operations
            ),
        )
    if isinstance(value, _QuantumParallelFragment):
        return replace(
            value,
            branches=tuple(
                _expand_fragment_calls(branch, bindings, stack=stack)
                for branch in value.branches
            ),
        )
    if isinstance(value, _QuantumRepeatFragment):
        return replace(
            value,
            operation=_expand_fragment_calls(value.operation, bindings, stack=stack),
        )
    if isinstance(value, _QuantumConditionalFragment):
        return replace(
            value,
            when_true=_expand_fragment_calls(value.when_true, bindings, stack=stack),
            when_false=_expand_fragment_calls(value.when_false, bindings, stack=stack),
        )
    return value


def _evaluate_fragment_call(
    call: _FragmentCall,
    bindings: Mapping[str, object],
) -> QuantumFragment:
    resolved: dict[str, object] = {}
    for (name, actual), formal in zip(
        call.arguments,
        call.definition.parameters,
        strict=True,
    ):
        if isinstance(formal, Qubit | Coupler):
            resolved[name] = actual
            continue
        selected = bindings[actual.id] if isinstance(actual, ProgramInput) else actual
        try:
            resolved[name] = coerce_literal(
                _program_input_type(formal, non_negative=False),
                selected,
                path=("fragment", call.definition.id, name),
            )
        except ValueValidationError as error:
            raise ProgramBindingError(str(error)) from error
    return call.definition.__wrapped__(**resolved)


def _validate_expanded_fragment(
    call: _FragmentCall,
    body: QuantumFragment,
) -> None:
    facts = _summarize_fragment(body)
    if facts.results:
        msg = f"quantum fragment {call.definition.id!r} cannot produce results"
        raise ValueError(msg)
    if facts.inputs:
        rendered = ", ".join(repr(value.id) for value in facts.inputs)
        msg = (
            f"quantum fragment {call.definition.id!r} captures unbound inputs: "
            f"{rendered}"
        )
        raise ValueError(msg)
    allowed_elements = {
        (type(value), value.id)
        for _name, value in call.arguments
        if isinstance(value, Qubit | Coupler)
    }
    foreign_elements = {
        (type(value), value.id) for value in facts.element_uses
    } - allowed_elements
    if foreign_elements:
        rendered = ", ".join(
            repr(element_id)
            for _element_type, element_id in sorted(
                foreign_elements,
                key=lambda item: (item[0].__name__, item[1]),
            )
        )
        msg = (
            f"quantum fragment {call.definition.id!r} captures undeclared "
            f"elements: {rendered}"
        )
        raise ValueError(msg)
