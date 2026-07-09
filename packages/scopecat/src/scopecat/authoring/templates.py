"""High-level experiment authoring template invocations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from scopecat.authoring.expressions import (
    Expression,
)
from scopecat.experiments import (
    ParameterScanAxis,
    RunRequest,
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
        ExperimentAssembly,
        ExperimentModule,
        ModuleBuilder,
        ProductSelectionIntent,
    )

    type TemplateSource = ExperimentModule | ModuleBuilder
    type TemplateRecordSelection = ProductSelectionIntent
else:
    type TemplateSource = object
    type TemplateRecordSelection = object

type TemplateBuild = Callable[..., object]
type ConfigProfileInput = str | Path | ConfigProfileSnapshot


def _object_dict() -> dict[str, object]:
    return {}


@dataclass(frozen=True)
class InputDescription:
    id: str
    kind: str | None = None
    default: object | None = None
    label: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentTemplate:
    id: str
    experiment_id: str | None = None
    kind: str | None = None
    sources: Sequence[TemplateSource] = ()
    record_selections: tuple[TemplateRecordSelection, ...] = ()
    inputs: tuple[InputDescription, ...] = ()
    defaults: dict[str, object] = field(default_factory=_object_dict)
    default_scans: tuple[ScanItem, ...] = ()
    parameter_derivations: ParameterDerivationSet | None = None
    label: str | None = None
    description: str | None = None
    metadata: dict[str, object] = field(default_factory=_object_dict)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "experiment template id must be non-empty"
            raise ValueError(msg)
        if not self.sources:
            msg = "experiment template requires sources"
            raise ValueError(msg)
        if not self.kind:
            msg = "experiment template sources require kind"
            raise ValueError(msg)

    def bind(self, **inputs: object) -> ExperimentInvocation:
        return ExperimentInvocation(
            compile=_source_template_compile(self),
            build_inputs=dict(inputs),
            request=RunRequest(
                id=f"{self.id}.request",
                template_id=self.id,
                template_inputs=materialize_request_inputs(inputs),
            ),
            defaults=self.defaults,
            input_descriptions=self.inputs,
            default_scans=self.default_scans,
            parameter_derivations=self.parameter_derivations,
            template=self,
        )


@dataclass(frozen=True)
class ExperimentInvocation:
    compile: TemplateBuild
    request: RunRequest
    build_inputs: dict[str, object] = field(default_factory=_object_dict)
    scans: tuple[ScanItem, ...] = ()
    default_scans: tuple[ScanItem, ...] = ()
    defaults: dict[str, object] = field(default_factory=_object_dict)
    input_descriptions: tuple[InputDescription, ...] = ()
    parameter_derivations: ParameterDerivationSet | None = None
    template: ExperimentTemplate | None = None

    def bind(self, **inputs: object) -> ExperimentInvocation:
        build_inputs = dict(self.build_inputs)
        build_inputs.update(inputs)
        template_inputs = dict(self.request.template_inputs)
        template_inputs.update(materialize_request_inputs(inputs))
        return replace(
            self,
            build_inputs=build_inputs,
            request=self.request.model_copy(
                update={"template_inputs": template_inputs}
            ),
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

    def _replace_request(self, request: RunRequest) -> ExperimentInvocation:
        return replace(self, request=request)


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
    _sources: tuple[TemplateSource, ...] = ()
    _record_selections: tuple[TemplateRecordSelection, ...] = ()
    _inputs: tuple[InputDescription, ...] = ()
    _defaults: dict[str, object] = field(default_factory=_object_dict)
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
            sources=self._sources,
            record_selections=self._record_selections,
            inputs=self._inputs,
            defaults=self._defaults,
            default_scans=self._default_scans,
            parameter_derivations=self._parameter_derivations,
            label=self._label,
            description=self._description,
            metadata=self._metadata,
        )

    def experiment_id(self, experiment_id: str) -> TemplateBuilder:
        return replace(self, _experiment_id=experiment_id)

    def use(self, *sources: TemplateSource) -> TemplateBuilder:
        from scopecat.authoring.assembly import ExperimentModule, ModuleBuilder

        for source in cast("tuple[object, ...]", sources):
            if not isinstance(source, ExperimentModule | ModuleBuilder):
                msg = "template use() accepts ExperimentModule or ModuleBuilder sources"
                raise TypeError(msg)
        return replace(self, _sources=(*self._sources, *sources))

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
        default: object | None = None,
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
        defaults = dict(self._defaults)
        if default is not None:
            defaults[id] = default
        return replace(self, _inputs=inputs, _defaults=defaults)

    def inputs(self, *inputs: InputDescription) -> TemplateBuilder:
        defaults = dict(self._defaults)
        for selected in inputs:
            if selected.default is not None:
                defaults[selected.id] = selected.default
        return replace(self, _inputs=(*self._inputs, *inputs), _defaults=defaults)

    def defaults(self, **defaults: object) -> TemplateBuilder:
        return replace(self, _defaults={**self._defaults, **defaults})

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


def template(
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
        _experiment_id=experiment_id,
        _parameter_derivations=parameter_derivations,
        _label=label,
        _description=description,
        _metadata=dict(metadata or {}),
    )


def _source_template_compile(template: ExperimentTemplate) -> TemplateBuild:
    def assemble(**inputs: object) -> ExperimentAssembly:
        from scopecat.authoring.assembly import (
            ExperimentAssembly,
            ExperimentModule,
        )

        assemblies: list[ExperimentAssembly] = []
        for source in template.sources:
            if isinstance(source, ExperimentModule):
                assemblies.append(source(**inputs).assemble())
            else:
                assemblies.append(source.build()(**inputs).assemble())
        if template.record_selections:
            assemblies.append(
                ExperimentAssembly(
                    entity_inputs=(),
                    record_selections=template.record_selections,
                )
            )
        return ExperimentAssembly.combine(
            experiment_id=template.experiment_id or template.id,
            kind=template.kind or template.id,
            assemblies=assemblies,
            metadata=template.metadata,
        )

    return assemble


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
    "template",
]
