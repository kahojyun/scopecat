"""Immutable experiment definitions and invocation values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.value_types import ValueType
from scopecat.program.bindings import (
    EnsureStateIntent,
    ExperimentBindingIntent,
)
from scopecat.program.module import (
    ModuleBodyIR,
    ModuleInterfaceIR,
    ModulePythonImplementation,
)
from scopecat.program.products import RecordSelection
from scopecat.program.scans import Scan
from scopecat.program.value_refs import (
    capture_runtime_inputs,
    empty_frozen_mapping,
)
from scopecat.program.values import (
    MetadataValue,
    RuntimeInput,
)
from scopecat.program.verification import (
    validate_experiment_definition,
    validate_experiment_inputs,
)


class _InputDefaultMissing:
    __slots__ = ()


_INPUT_DEFAULT_MISSING = _InputDefaultMissing()


@dataclass(frozen=True, slots=True)
class ExperimentInputDef:
    """One normalized experiment input consumed by binding and compilation."""

    id: str
    value_type: ValueType | None
    required: bool = False
    default: RuntimeInput | _InputDefaultMissing = _INPUT_DEFAULT_MISSING

    @property
    def has_default(self) -> bool:
        return self.default is not _INPUT_DEFAULT_MISSING


@dataclass(frozen=True, slots=True)
class ExperimentDef:
    """Canonical config-free root and policy shared by every invocation path.

    Unlike a reusable :class:`ModuleDef`, the root body may consume experiment
    coordinates and parameter expressions directly.
    """

    id: str
    kind: str
    interface: ModuleInterfaceIR
    body: ModuleBodyIR
    python_implementations: tuple[ModulePythonImplementation, ...] = ()
    inputs: tuple[ExperimentInputDef, ...] = ()
    default_scans: tuple[Scan, ...] = ()
    record_selections: tuple[RecordSelection, ...] = ()
    final_state: EnsureStateIntent | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        product_ids = tuple(
            product.qualified_id for product in self.body.exposed_products
        )
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("experiment definition contains duplicate product ids")
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentInvocation:
    definition: ExperimentDef
    inputs: Mapping[str, RuntimeInput] = field(default_factory=empty_frozen_mapping)
    scans: tuple[Scan, ...] = ()

    def bind(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        captured_inputs = capture_experiment_inputs(inputs)
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


def create_experiment_def(
    *,
    id: str,
    kind: str,
    interface: ModuleInterfaceIR,
    body: ModuleBodyIR,
    python_implementations: Sequence[ModulePythonImplementation] = (),
    record_selections: Sequence[RecordSelection] = (),
    input_defaults: Mapping[str, RuntimeInput] | None = None,
    required_inputs: Sequence[str] = (),
    default_scans: Sequence[Scan] = (),
    final_state_bindings: Sequence[ExperimentBindingIntent] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentDef:
    """Normalize all experiment semantics at one immutable boundary."""

    if not id:
        msg = "experiment definition id must be non-empty"
        raise ValueError(msg)
    if not kind:
        msg = "experiment definition requires kind"
        raise ValueError(msg)
    selected_records = tuple(record_selections)
    selected_scans = tuple(default_scans)
    selected_defaults = capture_experiment_inputs(input_defaults or {})
    selected_required = tuple(required_inputs)
    input_types = validate_experiment_definition(
        input_ports=interface.imports,
        defaults=selected_defaults,
        default_scans=selected_scans,
    )
    program_input_ids = tuple(port.id for port in interface.imports)
    input_ids = tuple(
        dict.fromkeys(
            (
                *program_input_ids,
                *selected_defaults,
                *selected_required,
                *input_types,
            )
        )
    )
    normalized_inputs = tuple(
        ExperimentInputDef(
            id=input_id,
            value_type=input_types.get(input_id),
            required=input_id in selected_required,
            default=selected_defaults.get(input_id, _INPUT_DEFAULT_MISSING),
        )
        for input_id in input_ids
    )
    return ExperimentDef(
        id=id,
        kind=kind,
        interface=interface,
        body=body,
        python_implementations=tuple(python_implementations),
        inputs=normalized_inputs,
        default_scans=selected_scans,
        record_selections=selected_records,
        final_state=(
            EnsureStateIntent(tuple(final_state_bindings))
            if final_state_bindings
            else None
        ),
        metadata=freeze_json_mapping(metadata or {}),
    )


def capture_experiment_inputs(
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
