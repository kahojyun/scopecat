"""High-level experiment authoring drafts and templates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from scopecat.authoring.expressions import (
    ExperimentVariable,
    Expression,
    linspace,
)
from scopecat.config_profiles import load_config_profile
from scopecat.config_registry import resolve_config_registry_config_source
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription
from scopecat.models.run import RunConfigSource
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.units import compatible_units, from_base_value, to_base_value

type TemplateBuild = Callable[..., ExperimentSpec]
type ConfigProfileInput = str | Path | ConfigProfileSnapshot


def _object_dict() -> dict[str, object]:
    return {}


@dataclass(frozen=True)
class AroundSweep:
    parameter_id: str
    span: Expression | Quantity
    points: int


@dataclass(frozen=True)
class ExperimentTemplate:
    id: str
    build: TemplateBuild
    inputs: tuple[ProviderOptionDescription, ...] = ()
    defaults: dict[str, object] = field(default_factory=_object_dict)
    label: str | None = None
    description: str | None = None
    metadata: dict[str, object] = field(default_factory=_object_dict)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "experiment template id must be non-empty"
            raise ValueError(msg)

    def __call__(self, **inputs: object) -> ExperimentDraft:
        return ExperimentDraft(
            build=self.build,
            inputs=dict(inputs),
            template_id=self.id,
            defaults=self.defaults,
            input_descriptions=self.inputs,
            template=self,
        )


@dataclass(frozen=True)
class ExperimentDraft:
    build: TemplateBuild
    inputs: dict[str, object] = field(default_factory=_object_dict)
    template_id: str | None = None
    defaults: dict[str, object] = field(default_factory=_object_dict)
    input_descriptions: tuple[ProviderOptionDescription, ...] = ()
    template: ExperimentTemplate | None = None


@dataclass(frozen=True)
class ResolvedExperiment:
    experiment: ExperimentSpec
    template_id: str | None
    inputs: dict[str, object]
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass
class ExperimentAuthoringContext:
    config: ConfigProfileSnapshot
    workspace: Path
    config_source: RunConfigSource | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def require_subject(self, subject_id: str) -> str:
        known_subjects = {
            device.id for device in self.config.device_topology.devices
        } | {channel.id for channel in self.config.device_topology.channels}
        if subject_id not in known_subjects:
            self.raise_diagnostic(
                "unknown_authoring_subject",
                f"experiment authoring references unknown subject {subject_id}",
                "subject",
            )
        return subject_id

    def require_parameter(self, parameter_id: str) -> Quantity:
        if self.config.parameter_build is None:
            self.raise_diagnostic(
                "missing_parameter_build",
                "experiment authoring requires a parameter build snapshot",
                "parameter_build",
            )
        parameter = self.config.parameter_build.get(parameter_id)
        if parameter is None:
            self.raise_diagnostic(
                "unknown_authoring_parameter",
                f"experiment authoring references unknown parameter {parameter_id}",
                "parameter",
            )
        return parameter.quantity

    def require_resource(self, resource_id: str) -> str:
        if resource_id not in {
            instrument.id for instrument in self.config.instrument_registry.instruments
        }:
            self.raise_diagnostic(
                "unknown_authoring_resource",
                f"experiment authoring references unknown resource {resource_id}",
                "resource",
            )
        return resource_id

    def require_capability(self, resource_id: str, capability_id: str) -> str:
        resource = next(
            (
                instrument
                for instrument in self.config.instrument_registry.instruments
                if instrument.id == resource_id
            ),
            None,
        )
        if resource is None:
            self.raise_diagnostic(
                "unknown_authoring_resource",
                f"experiment authoring references unknown resource {resource_id}",
                "resource",
            )
        if capability_id not in resource.capabilities:
            self.raise_diagnostic(
                "unknown_authoring_capability",
                f"resource {resource_id} does not expose capability {capability_id}",
                "capability",
            )
        return capability_id

    def require_binding_capability(self, resource_id: str, capability_id: str) -> None:
        self.require_resource(resource_id)
        self.require_capability(resource_id, capability_id)

    def around_sweep(
        self,
        sweep: AroundSweep | None,
        *,
        parameter_id: str,
        default_span: Quantity,
        default_points: int,
    ) -> ExperimentVariable:
        selected = sweep or AroundSweep(
            parameter_id=parameter_id,
            span=default_span,
            points=default_points,
        )
        if selected.parameter_id != parameter_id:
            self.raise_diagnostic(
                "authoring_sweep_parameter_mismatch",
                f"sweep parameter must be {parameter_id}",
                "sweep.parameter_id",
            )
        if selected.points < 2:
            self.raise_diagnostic(
                "authoring_points_invalid",
                "sweep points must be at least 2",
                "sweep.points",
            )
        center = self.require_parameter(parameter_id)
        span = _quantity_from_value(selected.span)
        if not compatible_units(center.unit, span.unit):
            self.raise_diagnostic(
                "authoring_sweep_span_unit_mismatch",
                f"sweep span unit {span.unit} is not compatible with {center.unit}",
                "sweep.span",
            )
        center_base = to_base_value(center.value, center.unit)
        span_base = to_base_value(span.value, span.unit)
        if center_base is None or span_base is None:
            self.raise_diagnostic(
                "authoring_sweep_unit_not_convertible",
                "sweep center and span must use linearly convertible units",
                "sweep.span",
            )
        start = from_base_value(center_base - span_base / 2, center.unit)
        stop = from_base_value(center_base + span_base / 2, center.unit)
        if start is None or stop is None:
            self.raise_diagnostic(
                "authoring_sweep_unit_not_convertible",
                "sweep center and span must use linearly convertible units",
                "sweep.span",
            )
        return linspace(start, stop, selected.points, unit=center.unit)

    def diagnostic(
        self,
        severity: DiagnosticSeverity,
        code: str,
        message: str,
        path: str | None = None,
    ) -> Diagnostic:
        return Diagnostic(
            severity=severity,
            code=code,
            message=message,
            path=path,
        )

    def raise_diagnostic(
        self, code: str, message: str, path: str | None = None
    ) -> NoReturn:
        raise ValidationFailed([self.diagnostic("error", code, message, path)])


@dataclass
class TemplateRegistry:
    _templates: dict[str, ExperimentTemplate] = field(default_factory=dict)

    def register(self, experiment_template: ExperimentTemplate) -> ExperimentTemplate:
        if experiment_template.id in self._templates:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "experiment_template_duplicate",
                        f"experiment template already registered: "
                        f"{experiment_template.id}",
                        "template.id",
                    )
                ]
            )
        self._templates[experiment_template.id] = experiment_template
        return experiment_template

    def get(self, template_id: str) -> ExperimentTemplate:
        template = self._templates.get(template_id)
        if template is None:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "experiment_template_not_found",
                        f"experiment template not found: {template_id}",
                        "template.id",
                    )
                ]
            )
        return template

    def list(self) -> tuple[ExperimentTemplate, ...]:
        return tuple(
            self._templates[template_id] for template_id in sorted(self._templates)
        )

    def build(self, template_id: str, **inputs: object) -> ExperimentDraft:
        return self.get(template_id)(**inputs)


def template(
    *,
    id: str,  # noqa: A002
    build: TemplateBuild,
    inputs: tuple[ProviderOptionDescription, ...] = (),
    defaults: Mapping[str, object] | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> ExperimentTemplate:
    return ExperimentTemplate(
        id=id,
        build=build,
        inputs=inputs,
        defaults=dict(defaults or {}),
        label=label,
        description=description,
        metadata=dict(metadata or {}),
    )


def around(
    parameter_id: str,
    *,
    span: Expression | Quantity,
    points: int,
) -> AroundSweep:
    return AroundSweep(parameter_id=parameter_id, span=span, points=points)


def resolve_experiment(
    experiment: ExperimentDraft,
    *,
    workspace: str | Path,
    config_entry: str | None = "active",
    config_profile: ConfigProfileInput | None = None,
) -> ResolvedExperiment:
    config, source = _resolve_config_source(
        workspace=workspace,
        config_entry=config_entry,
        config_profile=config_profile,
    )
    return resolve_experiment_with_config(
        experiment,
        config=config,
        workspace=workspace,
        config_source=source,
    )


def resolve_experiment_with_config(
    experiment: ExperimentDraft,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
) -> ResolvedExperiment:
    return _resolve_draft(
        experiment,
        config=config,
        workspace=workspace,
        config_source=config_source,
    )


_GLOBAL_REGISTRY = TemplateRegistry()


def registry() -> TemplateRegistry:
    return _GLOBAL_REGISTRY


def _resolve_draft(
    draft: ExperimentDraft,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
) -> ResolvedExperiment:
    inputs = _merged_inputs(draft)
    context = ExperimentAuthoringContext(
        config=config,
        workspace=Path(workspace),
        config_source=config_source,
    )
    try:
        experiment = draft.build(context, **inputs)
    except ValidationFailed:
        raise
    except Exception as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "experiment_authoring_build_failed",
                    "experiment authoring build failed: "
                    f"{type(error).__name__}: {error}",
                    "authoring",
                )
            ]
        ) from error
    return _resolved_spec(
        experiment,
        config=config,
        workspace=workspace,
        config_source=config_source,
        template_id=draft.template_id,
        inputs=inputs,
        authoring_diagnostics=context.diagnostics,
    )


def _resolved_spec(
    experiment: ExperimentSpec,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
    template_id: str | None,
    inputs: Mapping[str, object],
    authoring_diagnostics: list[Diagnostic] | None = None,
) -> ResolvedExperiment:
    del workspace
    diagnostics = list(authoring_diagnostics or [])
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    return ResolvedExperiment(
        experiment=experiment,
        template_id=template_id,
        inputs=dict(inputs),
        config=config,
        config_source=config_source,
        diagnostics=tuple(diagnostics),
    )


def _merged_inputs(draft: ExperimentDraft) -> dict[str, object]:
    merged = dict(draft.defaults)
    merged.update(draft.inputs)
    missing = [
        option.id
        for option in draft.input_descriptions
        if option.required and merged.get(option.id) is None
    ]
    if missing:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "experiment_template_missing_input",
                    "experiment template missing required input: " + ", ".join(missing),
                    "template.inputs",
                )
            ]
        )
    return merged


def _resolve_config_source(
    *,
    workspace: str | Path,
    config_entry: str | None,
    config_profile: ConfigProfileInput | None,
) -> tuple[ConfigProfileSnapshot, RunConfigSource | None]:
    if config_profile is not None:
        if config_entry not in (None, "active"):
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "conflicting_experiment_authoring_config_source",
                        "provide either config_profile or config_entry, not both",
                        "config",
                    )
                ]
            )
        if isinstance(config_profile, ConfigProfileSnapshot):
            return config_profile, None
        return load_config_profile(config_profile), None
    if config_entry is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_experiment_authoring_config_source",
                    "provide config_profile or config_entry",
                    "config",
                )
            ]
        )
    return resolve_config_registry_config_source(
        selector=config_entry,
        workspace=workspace,
    )


def _quantity_from_value(value: Expression | Quantity) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if value.kind == "quantity" and value.quantity is not None:
        return value.quantity
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "authoring_value_not_quantity",
                "authoring value must be a quantity literal",
                "value",
            )
        ]
    )


def _diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "AroundSweep",
    "ExperimentAuthoringContext",
    "ExperimentDraft",
    "ExperimentTemplate",
    "ResolvedExperiment",
    "TemplateRegistry",
    "around",
    "registry",
    "resolve_experiment",
    "resolve_experiment_with_config",
    "template",
]
