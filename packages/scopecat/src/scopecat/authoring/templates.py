"""High-level experiment authoring template invocations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from scopecat.authoring.context import (
    AroundSweep,
)
from scopecat.authoring.expressions import (
    Expression,
)
from scopecat.experiments import (
    RunRequest,
    RunSweep,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.parameters import ParameterDerivationSet
from scopecat.relations import ScalarExpr

if TYPE_CHECKING:
    from scopecat.authoring.assembly import (
        ExperimentAssembly,
    )

type TemplateBuild = Callable[..., object]
type ConfigProfileInput = str | Path | ConfigProfileSnapshot
type TemplateSource = object


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
    sources: Sequence[TemplateSource] = ((),)
    inputs: tuple[InputDescription, ...] = ()
    defaults: dict[str, object] = field(default_factory=_object_dict)
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

    def __call__(self, **inputs: object) -> ExperimentInvocation:
        return self.bind(**inputs)

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
            parameter_derivations=self.parameter_derivations,
            template=self,
        )

    def scan(
        self,
        parameter_id: str,
        *,
        span: Expression | Quantity,
        points: int,
        input_id: str | None = None,
    ) -> ExperimentInvocation:
        return self.bind().scan(
            parameter_id,
            span=span,
            points=points,
            input_id=input_id,
        )


@dataclass(frozen=True)
class ExperimentInvocation:
    compile: TemplateBuild
    request: RunRequest
    build_inputs: dict[str, object] = field(default_factory=_object_dict)
    runtime_sweeps: tuple[RunSweep, ...] = ()
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
        parameter_id: str,
        *,
        span: Expression | Quantity,
        points: int,
        input_id: str | None = None,
    ) -> ExperimentInvocation:
        selected = AroundSweep(parameter_id=parameter_id, span=span, points=points)
        return self._with_scan_input(input_id or parameter_id, selected)

    def extra(self, *sweeps: RunSweep) -> ExperimentInvocation:
        return replace(self, runtime_sweeps=(*self.runtime_sweeps, *sweeps))

    def _with_scan_input(
        self,
        input_id: str,
        selected: AroundSweep,
    ) -> ExperimentInvocation:
        bound = self.bind(**{input_id: selected})
        request = bound.request
        point_axes = dict(request.point_axes)
        parameter_sweeps = [
            record
            for record in request.parameter_sweeps
            if record.get("parameter_id") != selected.parameter_id
        ]
        record = _around_sweep_request_record(selected)
        point_axes[selected.parameter_id] = record
        parameter_sweeps.append(record)
        return bound._replace_request(
            request.model_copy(
                update={
                    "point_axes": point_axes,
                    "parameter_sweeps": parameter_sweeps,
                }
            )
        )

    def _replace_request(self, request: RunRequest) -> ExperimentInvocation:
        return replace(self, request=request)


@dataclass(frozen=True)
class TemplateBuilder:
    """Fluent builder for reusable experiment shapes.

    Templates sit above modules because sweeps and product selection are part
    of an experiment shape, not a reusable component. Keeping those choices
    here lets the same module participate in multiple calibrated workflows.
    """

    id: str
    kind: str
    _experiment_id: str | None = None
    _sources: tuple[TemplateSource, ...] = ()
    _inputs: tuple[InputDescription, ...] = ()
    _defaults: dict[str, object] = field(default_factory=_object_dict)
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

    def __call__(self, **inputs: object) -> ExperimentInvocation:
        return self.bind(**inputs)

    def bind(self, **inputs: object) -> ExperimentInvocation:
        return self.build().bind(**inputs)

    def build(self) -> ExperimentTemplate:
        return ExperimentTemplate(
            id=self.id,
            experiment_id=self._experiment_id,
            kind=self.kind,
            sources=self._sources,
            inputs=self._inputs,
            defaults=self._defaults,
            parameter_derivations=self._parameter_derivations,
            label=self._label,
            description=self._description,
            metadata=self._metadata,
        )

    def experiment_id(self, experiment_id: str) -> TemplateBuilder:
        return replace(self, _experiment_id=experiment_id)

    def use(self, *sources: TemplateSource) -> TemplateBuilder:
        return replace(self, _sources=(*self._sources, *sources))

    def points(self, *sources: TemplateSource) -> TemplateBuilder:
        return self.use(*sources)

    def scan_around(
        self,
        axis_id: str,
        *,
        center: ScalarExpr,
        span: Quantity,
        points: int,
        input_id: str | None = None,
    ) -> TemplateBuilder:
        from scopecat.authoring.assembly import around_points

        return self.points(
            around_points(
                axis_id,
                center=center,
                default_span=span,
                points=points,
                input_id=input_id,
            )
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

        return self.use(
            *(
                record_product(
                    product_id,
                    record_id=record_id,
                    metadata=metadata,
                )
                for product_id in product_ids
            )
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


def around(
    parameter_id: str,
    *,
    span: Expression | Quantity,
    points: int,
) -> AroundSweep:
    return AroundSweep(parameter_id=parameter_id, span=span, points=points)


def _source_template_compile(template: ExperimentTemplate) -> TemplateBuild:
    def assemble(**inputs: object) -> ExperimentAssembly:
        from scopecat.authoring.assembly import ExperimentAssembly, ExperimentModule
        from scopecat.authoring.resolution import compile_composed_source

        assemblies: list[ExperimentAssembly] = []
        for source in template.sources:
            if isinstance(source, ExperimentModule):
                assemblies.append(source(**inputs).assemble())
            else:
                assemblies.append(compile_composed_source(source))
        return ExperimentAssembly.combine(
            experiment_id=template.experiment_id or template.id,
            kind=template.kind or template.id,
            assemblies=assemblies,
            metadata=template.metadata,
        )

    return assemble


def materialize_request_inputs(inputs: Mapping[str, object]) -> dict[str, object]:
    return {key: _request_value(value) for key, value in inputs.items()}


def _around_sweep_request_record(sweep: AroundSweep) -> dict[str, object]:
    return {
        "parameter_id": sweep.parameter_id,
        "around": "active",
        "span": _request_value(sweep.span),
        "points": sweep.points,
    }


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
    "AroundSweep",
    "ExperimentInvocation",
    "ExperimentTemplate",
    "InputDescription",
    "TemplateBuilder",
    "around",
    "materialize_request_inputs",
    "template",
]
