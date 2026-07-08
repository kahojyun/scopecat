"""Config-dependent authoring context used while linking assemblies."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from scopecat.authoring.expressions import ExperimentVariable, Expression, linspace
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.entity import EntityArray, EntityRef, entity_ref
from scopecat.models.parameter import ParameterViewSnapshot, Quantity
from scopecat.models.run import RunConfigSource
from scopecat.units import compatible_units, from_base_value, to_base_value


@dataclass(frozen=True)
class AroundSweep:
    parameter_id: str
    span: Expression | Quantity
    points: int


@dataclass
class ExperimentAuthoringContext:
    config: ConfigProfileSnapshot
    parameter_view: ParameterViewSnapshot
    workspace: Path
    config_source: RunConfigSource | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def require_entity(self, entity: EntityRef | str) -> EntityRef:
        selected = entity_ref(entity)
        known = self.config.topology.entity(selected.id)
        if known is None:
            self.raise_diagnostic(
                "unknown_authoring_entity",
                f"experiment authoring references unknown entity {selected.id}",
                "entity",
            )
        if (
            selected.kind is not None
            and known.kind is not None
            and selected.kind != known.kind
        ):
            self.raise_diagnostic(
                "authoring_entity_kind_mismatch",
                f"entity {selected.id} has kind {known.kind}, not {selected.kind}",
                "entity",
            )
        return EntityRef(
            id=selected.id,
            kind=selected.kind or known.kind,
            metadata={**known.metadata, **selected.metadata},
        )

    def require_entity_array(self, entities: EntityArray) -> EntityArray:
        resolved = tuple(self.require_entity(entity) for entity in entities.entities)
        return EntityArray(
            entities=resolved,
            kind=entities.kind or _common_entity_kind(resolved),
            metadata=dict(entities.metadata),
        )

    def require_parameter(self, parameter_id: str) -> Quantity:
        parameter = self.parameter_view.get(parameter_id)
        if parameter is None:
            self.raise_diagnostic(
                "unknown_authoring_parameter",
                f"experiment authoring references unknown parameter {parameter_id}",
                "parameter",
            )
        return parameter.quantity

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
        return diagnostic(severity, code, message, path)

    def raise_diagnostic(
        self, code: str, message: str, path: str | None = None
    ) -> NoReturn:
        raise ValidationFailed([self.diagnostic("error", code, message, path)])


def _quantity_from_value(value: Expression | Quantity) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if value.kind == "quantity" and value.quantity is not None:
        return value.quantity
    raise ValidationFailed(
        [
            diagnostic(
                "error",
                "authoring_value_not_quantity",
                "authoring value must be a quantity literal",
                "value",
            )
        ]
    )


def _common_entity_kind(entities: tuple[EntityRef, ...]) -> str | None:
    kinds = {entity.kind for entity in entities if entity.kind is not None}
    if len(kinds) == 1:
        return next(iter(kinds))
    return None


def diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "AroundSweep",
    "ExperimentAuthoringContext",
    "diagnostic",
]
