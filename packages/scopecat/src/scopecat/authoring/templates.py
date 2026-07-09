"""High-level experiment authoring template invocations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from scopecat.authoring.expressions import (
    Expression,
)
from scopecat.experiments import (
    ParameterScanAxis,
    ScanAxis,
    ScanGroup,
    ScanItem,
    axis,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.parameters import ParameterDerivationSet
from scopecat.relations import ScalarExpr, param

if TYPE_CHECKING:
    from scopecat.authoring.assembly import (
        ExperimentModule,
        ProductSelectionIntent,
    )

    type TemplateModule = ExperimentModule
    type TemplateRecordSelection = ProductSelectionIntent
else:
    type TemplateModule = object
    type TemplateRecordSelection = object

type ConfigProfileInput = str | Path | ConfigProfileSnapshot


def _object_dict() -> dict[str, object]:
    return {}


class _InputDefaultMissing:
    __slots__ = ()


_INPUT_DEFAULT_MISSING = _InputDefaultMissing()


@dataclass(frozen=True)
class InputDescription:
    id: str
    kind: str | None = None
    default: object = _INPUT_DEFAULT_MISSING
    label: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_default(self) -> bool:
        return self.default is not _INPUT_DEFAULT_MISSING


@dataclass(frozen=True)
class ExperimentTemplate:
    id: str
    experiment_id: str | None = None
    kind: str | None = None
    module: TemplateModule | None = None
    record_selections: tuple[TemplateRecordSelection, ...] = ()
    inputs: tuple[InputDescription, ...] = ()
    default_scans: tuple[ScanItem, ...] = ()
    parameter_derivations: ParameterDerivationSet | None = None
    label: str | None = None
    description: str | None = None
    metadata: dict[str, object] = field(default_factory=_object_dict)

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

    def bind(self, **inputs: object) -> ExperimentInvocation:
        return ExperimentInvocation(
            template=self,
            inputs=dict(inputs),
        )


@dataclass(frozen=True)
class ExperimentInvocation:
    template: ExperimentTemplate
    inputs: dict[str, object] = field(default_factory=_object_dict)
    scans: tuple[ScanItem, ...] = ()

    def bind(self, **inputs: object) -> ExperimentInvocation:
        selected = dict(self.inputs)
        selected.update(inputs)
        return replace(
            self,
            inputs=selected,
        )

    def scan(
        self,
        target: str | ScanItem,
        values: Sequence[object] = (),
        *,
        unit: str | None = None,
        center: ScalarExpr | None = None,
        span: Expression | Quantity | str | None = None,
        points: int | None = None,
        input_id: str | None = None,
    ) -> ExperimentInvocation:
        selected = _scan_item(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
            input_id=input_id,
        )
        return replace(self, scans=(*self.scans, selected))


@dataclass(frozen=True)
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
    _default_scans: tuple[ScanItem, ...] = ()
    _parameter_derivations: ParameterDerivationSet | None = None
    _label: str | None = None
    _description: str | None = None
    _metadata: dict[str, object] = field(default_factory=_object_dict)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "experiment template id must be non-empty"
            raise ValueError(msg)
        if not self.kind:
            msg = "experiment template kind must be non-empty"
            raise ValueError(msg)

    def bind(self, **inputs: object) -> ExperimentInvocation:
        return self.build().bind(**inputs)

    def build(self) -> ExperimentTemplate:
        return ExperimentTemplate(
            id=self.id,
            experiment_id=self._experiment_id,
            kind=self.kind,
            module=self._module,
            record_selections=self._record_selections,
            inputs=self._inputs,
            default_scans=self._default_scans,
            parameter_derivations=self._parameter_derivations,
            label=self._label,
            description=self._description,
            metadata=self._metadata,
        )

    def experiment_id(self, experiment_id: str) -> TemplateBuilder:
        return replace(self, _experiment_id=experiment_id)

    def scan(
        self,
        target: str | ScanItem,
        values: Sequence[object] = (),
        *,
        unit: str | None = None,
        center: ScalarExpr | None = None,
        span: Expression | Quantity | str | None = None,
        points: int | None = None,
        input_id: str | None = None,
    ) -> TemplateBuilder:
        return replace(
            self,
            _default_scans=(
                *self._default_scans,
                _scan_item(
                    target,
                    values,
                    unit=unit,
                    center=center,
                    span=span,
                    points=points,
                    input_id=input_id,
                ),
            ),
        )

    def input(
        self,
        id: str,  # noqa: A002
        *,
        kind: str | None = None,
        default: object = _INPUT_DEFAULT_MISSING,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TemplateBuilder:
        inputs = (
            *self._inputs,
            InputDescription(
                id=id,
                kind=kind,
                default=default,
                label=label,
                description=description,
                metadata=dict(metadata or {}),
            ),
        )
        return replace(self, _inputs=inputs)

    def inputs(self, *inputs: InputDescription) -> TemplateBuilder:
        return replace(self, _inputs=(*self._inputs, *inputs))

    def record_product(
        self,
        *product_ids: str,
        record_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TemplateBuilder:
        if record_id is not None and len(product_ids) != 1:
            msg = "record_id can only be used with one product"
            raise ValueError(msg)
        from scopecat.authoring.assembly import record_product

        return replace(
            self,
            _record_selections=(
                *self._record_selections,
                *(
                    record_product(
                        product_id,
                        record_id=record_id,
                        metadata=metadata,
                    )
                    for product_id in product_ids
                ),
            ),
        )

    def parameter_derivations(
        self,
        derivations: ParameterDerivationSet | None,
    ) -> TemplateBuilder:
        return replace(self, _parameter_derivations=derivations)

    def label(self, label: str | None) -> TemplateBuilder:
        return replace(self, _label=label)

    def description(self, description: str | None) -> TemplateBuilder:
        return replace(self, _description=description)

    def metadata(self, **metadata: object) -> TemplateBuilder:
        return replace(self, _metadata={**self._metadata, **metadata})


def template_builder_from_module(
    module: TemplateModule,
    id: str,  # noqa: A002
    *,
    kind: str,
    experiment_id: str | None = None,
    parameter_derivations: ParameterDerivationSet | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> TemplateBuilder:
    return TemplateBuilder(
        id=id,
        kind=kind,
        _module=module,
        _experiment_id=experiment_id,
        _parameter_derivations=parameter_derivations,
        _label=label,
        _description=description,
        _metadata=dict(metadata or {}),
    )


def _scan_item(
    target: str | ScanItem,
    values: Sequence[object] = (),
    *,
    unit: str | None = None,
    center: ScalarExpr | None = None,
    span: Expression | Quantity | str | None = None,
    points: int | None = None,
    input_id: str | None = None,
) -> ScanItem:
    if isinstance(target, ScanAxis | ParameterScanAxis | ScanGroup):
        if (
            values
            or unit is not None
            or center is not None
            or span is not None
            or points is not None
            or input_id is not None
        ):
            msg = "scan item cannot be combined with scan construction arguments"
            raise ValueError(msg)
        return target
    if values:
        if center is not None or span is not None or points is not None:
            msg = "scan values cannot be combined with center/span/points"
            raise ValueError(msg)
        return axis(target, values=values, unit=unit, input_id=input_id)
    if span is None or points is None:
        msg = "scan requires values or span and points"
        raise ValueError(msg)
    return replace(
        axis(
            target,
            center=center or param(target),
            span=_scan_span_value(span),
            points=points,
            input_id=input_id,
        ),
        implicit_center=center is None,
    )


def _scan_span_value(value: Expression | Quantity | str) -> Quantity | str:
    if isinstance(value, Quantity | str):
        return value
    if value.kind == "quantity" and value.quantity is not None:
        return value.quantity
    msg = "scan span must be a quantity literal"
    raise ValueError(msg)


def materialize_request_inputs(inputs: Mapping[str, object]) -> dict[str, object]:
    return {key: _request_value(value) for key, value in inputs.items()}


def _request_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _request_mapping(cast("Mapping[object, object]", asdict(value)))
    if isinstance(value, Mapping):
        return _request_mapping(cast("Mapping[object, object]", value))
    if isinstance(value, list | tuple):
        return [
            _request_value(item)
            for item in cast("list[object] | tuple[object, ...]", value)
        ]
    return value


def _request_mapping(value: Mapping[object, object]) -> dict[str, object]:
    return {str(key): _request_value(item) for key, item in value.items()}


__all__ = [
    "ExperimentInvocation",
    "ExperimentTemplate",
    "InputDescription",
    "TemplateBuilder",
    "materialize_request_inputs",
]
