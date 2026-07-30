"""High-level experiment authoring template invocations."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.authoring._binding_intents import (
    EnsureStateIntent,
    ExperimentBindingIntent,
)
from scopecat.authoring._module_ir import ModuleIR
from scopecat.authoring._products import RecordSelection
from scopecat.authoring._validation import (
    validate_experiment_definition,
    validate_experiment_inputs,
)
from scopecat.authoring._value_refs import (
    capture_runtime_inputs,
    empty_frozen_mapping,
)
from scopecat.authoring.scans import Scan
from scopecat.authoring.values import (
    MetadataValue,
    RuntimeInput,
)
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.value_types import ValueType


class _InputDefaultMissing:
    __slots__ = ()


_INPUT_DEFAULT_MISSING = _InputDefaultMissing()


@dataclass(frozen=True, slots=True)
class ExperimentInput:
    """One normalized experiment input consumed by binding and compilation."""

    id: str
    value_type: ValueType | None
    required: bool = False
    default: RuntimeInput | _InputDefaultMissing = _INPUT_DEFAULT_MISSING

    @property
    def has_default(self) -> bool:
        return self.default is not _INPUT_DEFAULT_MISSING


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    """Canonical config-free definition shared by every invocation path."""

    id: str
    kind: str
    module: ModuleIR
    inputs: tuple[ExperimentInput, ...] = ()
    default_scans: tuple[Scan, ...] = ()
    record_selections: tuple[RecordSelection, ...] = ()
    postcondition: EnsureStateIntent | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentTemplate[**P]:
    """Callable UX for one canonical experiment definition."""

    definition: ExperimentDefinition
    _callable: Callable[P, object] = field(repr=False, compare=False)
    _signature: inspect.Signature = field(repr=False, compare=False)

    @property
    def __wrapped__(self) -> Callable[P, object]:
        return self._callable

    @property
    def __name__(self) -> str:
        return self._callable.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def bind(self, **inputs: object) -> ExperimentInvocation:
        """Partially bind named inputs; compilation checks completeness."""

        bound = self._signature.bind_partial(**inputs)
        return self._invocation(cast("dict[str, RuntimeInput]", dict(bound.arguments)))

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ExperimentInvocation:
        """Bind every required input through normal Python call semantics."""

        bound = self._signature.bind(*args, **kwargs)
        return self._invocation(cast("dict[str, RuntimeInput]", dict(bound.arguments)))

    def _invocation(
        self,
        inputs: Mapping[str, RuntimeInput],
    ) -> ExperimentInvocation:
        captured_inputs = _capture_experiment_inputs(inputs)
        validate_experiment_inputs(
            definitions=self.definition.inputs,
            inputs=captured_inputs,
        )
        return ExperimentInvocation(
            definition=self.definition,
            inputs=captured_inputs,
            scans=(),
        )


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentInvocation:
    definition: ExperimentDefinition
    inputs: Mapping[str, RuntimeInput] = field(default_factory=empty_frozen_mapping)
    scans: tuple[Scan, ...] = ()

    def bind(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        captured_inputs = _capture_experiment_inputs(inputs)
        validate_experiment_inputs(
            definitions=self.definition.inputs,
            inputs=captured_inputs,
        )
        selected = dict(self.inputs)
        selected.update(captured_inputs)
        return ExperimentInvocation(
            definition=self.definition,
            inputs=FrozenMapping(selected.items()),
            scans=self.scans,
        )

    def scan(
        self,
        *scans: Scan,
    ) -> ExperimentInvocation:
        return ExperimentInvocation(
            definition=self.definition,
            inputs=self.inputs,
            scans=(*self.scans, *scans),
        )


def create_experiment_definition_internal(
    *,
    id: str,
    kind: str,
    module: ModuleIR,
    record_selections: Sequence[RecordSelection] = (),
    input_defaults: Mapping[str, RuntimeInput] | None = None,
    required_inputs: Sequence[str] = (),
    default_scans: Sequence[Scan] = (),
    postcondition_bindings: Sequence[ExperimentBindingIntent] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentDefinition:
    """Normalize all experiment semantics at one immutable boundary."""

    if not id:
        msg = "experiment definition id must be non-empty"
        raise ValueError(msg)
    if not kind:
        msg = "experiment definition requires kind"
        raise ValueError(msg)
    selected_records = tuple(record_selections)
    selected_scans = tuple(default_scans)
    selected_defaults = _capture_experiment_inputs(input_defaults or {})
    selected_required = tuple(required_inputs)
    input_types = validate_experiment_definition(
        module=module,
        defaults=selected_defaults,
        default_scans=selected_scans,
    )
    module_input_ids = tuple(port.id for port in module.interface.imports)
    input_ids = tuple(
        dict.fromkeys(
            (
                *module_input_ids,
                *selected_defaults,
                *selected_required,
                *input_types,
            )
        )
    )
    normalized_inputs = tuple(
        ExperimentInput(
            id=input_id,
            value_type=input_types.get(input_id),
            required=input_id in selected_required,
            default=selected_defaults.get(input_id, _INPUT_DEFAULT_MISSING),
        )
        for input_id in input_ids
    )
    return ExperimentDefinition(
        id=id,
        kind=kind,
        module=module,
        inputs=normalized_inputs,
        default_scans=selected_scans,
        record_selections=selected_records,
        postcondition=(
            EnsureStateIntent(tuple(postcondition_bindings))
            if postcondition_bindings
            else None
        ),
        metadata=freeze_json_mapping(metadata or {}),
    )


def _capture_experiment_inputs(
    inputs: Mapping[str, RuntimeInput],
) -> Mapping[str, RuntimeInput]:
    try:
        captured = capture_runtime_inputs(cast("Mapping[str, object]", inputs))
    except (TypeError, ValueError) as error:
        selected = ", ".join(repr(input_id) for input_id in sorted(inputs))
        msg = (
            "experiment inputs require non-empty names and closed runtime data: "
            f"{selected}"
        )
        raise TypeError(msg) from error
    return cast("Mapping[str, RuntimeInput]", captured)
