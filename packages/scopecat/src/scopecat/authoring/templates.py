"""High-level experiment authoring template invocations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_runtime_input,
    freeze_runtime_inputs,
)
from scopecat.authoring._handles import create_handle, replace_handle
from scopecat.authoring._validation import (
    validate_template_bound_inputs,
    validate_template_definition,
)
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.scans import (
    Scan,
    ScanCenter,
    ScanValue,
    build_scan,
)
from scopecat.authoring.values import (
    MetadataValue,
    RuntimeInput,
    runtime_input_is_valid,
)
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity

if TYPE_CHECKING:
    from scopecat.authoring._record_intents import (
        ProductRef,
        ProductSelectionIntent,
        RecordSelection,
    )
    from scopecat.authoring.assembly import ExperimentModule

    type TemplateModule = ExperimentModule
    type TemplateRecordSelection = ProductSelectionIntent
else:
    type TemplateModule = object
    type TemplateRecordSelection = object

type ConfigProfileInput = str | Path | ConfigProfileSnapshot


class _InputDefaultMissing:
    __slots__ = ()


_INPUT_DEFAULT_MISSING = _InputDefaultMissing()


@dataclass(frozen=True)
class InputDescription:
    id: str
    default: RuntimeInput | _InputDefaultMissing = _INPUT_DEFAULT_MISSING
    label: str | None = None
    description: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "template input id must be non-empty"
            raise ValueError(msg)
        if self.has_default and not runtime_input_is_valid(self.default):
            msg = f"template input {self.id!r} default is not closed runtime data"
            raise TypeError(msg)
        if self.has_default:
            object.__setattr__(self, "default", freeze_runtime_input(self.default))
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def has_default(self) -> bool:
        return self.default is not _INPUT_DEFAULT_MISSING


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ExperimentTemplate:
    id: str
    experiment_id: str | None = None
    kind: str | None = None
    module: TemplateModule | None = None
    record_selections: tuple[TemplateRecordSelection, ...] = ()
    inputs: tuple[InputDescription, ...] = ()
    default_scans: tuple[Scan, ...] = ()
    label: str | None = None
    description: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __init__(self) -> None:
        msg = (
            "ExperimentTemplate is an opaque handle; create templates with "
            "module.template(...)"
        )
        raise TypeError(msg)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "experiment template id must be non-empty"
            raise ValueError(msg)
        if self.module is None:
            msg = "experiment template requires a module"
            raise ValueError(msg)
        if not self.kind:
            msg = "experiment template requires kind"
            raise ValueError(msg)

    def bind(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        _validate_runtime_inputs(inputs)
        if self.module is None:
            msg = "experiment template requires a module"
            raise ValueError(msg)
        validate_template_bound_inputs(
            module=self.module,
            descriptions=self.inputs,
            default_scans=self.default_scans,
            inputs=inputs,
        )
        return create_handle(
            ExperimentInvocation,
            template=self,
            inputs=freeze_runtime_inputs(inputs),
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ExperimentInvocation:
    template: ExperimentTemplate
    inputs: Mapping[str, RuntimeInput] = field(default_factory=empty_frozen_mapping)
    scans: tuple[Scan, ...] = ()

    def __init__(self) -> None:
        msg = (
            "ExperimentInvocation is an opaque handle; create invocations with "
            "template.bind(...)"
        )
        raise TypeError(msg)

    def bind(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        _validate_runtime_inputs(inputs)
        selected = dict(self.inputs)
        selected.update(inputs)
        module = self.template.module
        if module is None:
            msg = "experiment template requires a module"
            raise ValueError(msg)
        validate_template_bound_inputs(
            module=module,
            descriptions=self.template.inputs,
            default_scans=self.template.default_scans,
            inputs=selected,
        )
        return replace_handle(
            self,
            inputs=freeze_runtime_inputs(selected),
        )

    def scan(
        self,
        target: ValueRef | Scan,
        values: Sequence[ScanValue] = (),
        *,
        unit: str | None = None,
        center: ScanCenter | None = None,
        span: Quantity | str | None = None,
        points: int | None = None,
    ) -> ExperimentInvocation:
        selected = build_scan(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
        return replace_handle(self, scans=(*self.scans, selected))


@dataclass(frozen=True, slots=True, init=False, repr=False)
class TemplateBuilder:
    """Fluent builder for reusable experiment shapes.

    Templates sit above modules because scans and product selection are part
    of an experiment shape, not a reusable component. Keeping those choices
    here lets the same module participate in multiple calibrated workflows.
    """

    id: str
    kind: str
    _experiment_id: str | None = None
    _module: TemplateModule | None = None
    _record_selections: tuple[TemplateRecordSelection, ...] = ()
    _inputs: tuple[InputDescription, ...] = ()
    _default_scans: tuple[Scan, ...] = ()
    _label: str | None = None
    _description: str | None = None
    _metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __init__(self) -> None:
        msg = "TemplateBuilder is an opaque handle; create it with module.template(...)"
        raise TypeError(msg)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "experiment template id must be non-empty"
            raise ValueError(msg)
        if not self.kind:
            msg = "experiment template kind must be non-empty"
            raise ValueError(msg)

    def bind(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        return self.build().bind(**inputs)

    def build(self) -> ExperimentTemplate:
        template = create_handle(
            ExperimentTemplate,
            id=self.id,
            experiment_id=self._experiment_id,
            kind=self.kind,
            module=self._module,
            record_selections=self._record_selections,
            inputs=self._inputs,
            default_scans=self._default_scans,
            label=self._label,
            description=self._description,
            metadata=freeze_json_mapping(self._metadata),
        )
        if template.module is None:
            msg = "experiment template requires a module"
            raise ValueError(msg)
        validate_template_definition(
            module=template.module,
            inputs=template.inputs,
            default_scans=template.default_scans,
            record_selections=template.record_selections,
        )
        return template

    def experiment_id(self, experiment_id: str) -> TemplateBuilder:
        return replace_handle(self, _experiment_id=experiment_id)

    def scan(
        self,
        target: ValueRef | Scan,
        values: Sequence[ScanValue] = (),
        *,
        unit: str | None = None,
        center: ScanCenter | None = None,
        span: Quantity | str | None = None,
        points: int | None = None,
    ) -> TemplateBuilder:
        return replace_handle(
            self,
            _default_scans=(
                *self._default_scans,
                build_scan(
                    target,
                    values,
                    unit=unit,
                    center=center,
                    span=span,
                    points=points,
                ),
            ),
        )

    def input(
        self,
        id: str,  # noqa: A002
        *,
        default: RuntimeInput | _InputDefaultMissing = _INPUT_DEFAULT_MISSING,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> TemplateBuilder:
        inputs = (
            *self._inputs,
            InputDescription(
                id=id,
                default=default,
                label=label,
                description=description,
                metadata=freeze_json_mapping(metadata or {}),
            ),
        )
        return replace_handle(self, _inputs=inputs)

    def inputs(self, *inputs: InputDescription) -> TemplateBuilder:
        return replace_handle(self, _inputs=(*self._inputs, *inputs))

    def record_product(
        self,
        *products: str | ProductRef,
        record_id: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> TemplateBuilder:
        if record_id is not None and len(products) != 1:
            msg = "record_id can only be used with one product"
            raise ValueError(msg)
        from scopecat.authoring._record_intents import (
            product_selection_intent,
            record_product,
        )

        return replace_handle(
            self,
            _record_selections=(
                *self._record_selections,
                *(
                    product_selection_intent(
                        record_product(
                            product,
                            record_id=record_id,
                            metadata=metadata,
                        )
                    )
                    for product in products
                ),
            ),
        )

    def records(self, *selections: RecordSelection) -> TemplateBuilder:
        """Append explicit product-use record projections to this template."""

        return template_builder_with_record_selections_internal(self, selections)

    def label(self, label: str | None) -> TemplateBuilder:
        return replace_handle(self, _label=label)

    def description(self, description: str | None) -> TemplateBuilder:
        return replace_handle(self, _description=description)

    def metadata(self, **metadata: MetadataValue) -> TemplateBuilder:
        return replace_handle(
            self,
            _metadata=freeze_json_mapping({**self._metadata, **metadata}),
        )


def template_builder_from_module(
    module: TemplateModule,
    id: str,  # noqa: A002
    *,
    kind: str,
    experiment_id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> TemplateBuilder:
    return create_handle(
        TemplateBuilder,
        id=id,
        kind=kind,
        _module=module,
        _experiment_id=experiment_id,
        _label=label,
        _description=description,
        _metadata=freeze_json_mapping(metadata or {}),
    )


def template_builder_with_record_selections_internal(
    builder: TemplateBuilder,
    selections: Sequence[RecordSelection],
) -> TemplateBuilder:
    """Retain already-normalized selections across facade adaptation layers."""

    from scopecat.authoring._record_intents import product_selection_intent

    normalized = tuple(product_selection_intent(selection) for selection in selections)
    existing = cast(
        "tuple[ProductSelectionIntent, ...]",
        object.__getattribute__(builder, "_record_selections"),
    )
    return replace_handle(
        builder,
        _record_selections=(*existing, *normalized),
    )


def _validate_runtime_inputs(inputs: Mapping[str, RuntimeInput]) -> None:
    invalid = sorted(
        input_id
        for input_id, value in inputs.items()
        if not input_id or not runtime_input_is_valid(value)
    )
    if invalid:
        selected = ", ".join(repr(input_id) for input_id in invalid)
        msg = (
            "template inputs require non-empty names and closed runtime data: "
            f"{selected}"
        )
        raise TypeError(msg)


__all__ = [
    "ExperimentInvocation",
    "ExperimentTemplate",
    "InputDescription",
    "TemplateBuilder",
]
