"""Config-dependent authoring context used while linking assemblies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.entity import EntityRef, entity_ref
from scopecat.models.parameter import ParameterViewSnapshot, Quantity
from scopecat.models.run import RunConfigSource


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

    def require_entities(
        self,
        entities: Sequence[EntityRef | str],
    ) -> tuple[EntityRef, ...]:
        return tuple(self.require_entity(entity) for entity in entities)

    def require_parameter(self, parameter_id: str) -> Quantity:
        parameter = self.parameter_view.get(parameter_id)
        if parameter is None:
            self.raise_diagnostic(
                "unknown_authoring_parameter",
                f"experiment authoring references unknown parameter {parameter_id}",
                "parameter",
            )
        return parameter.quantity

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


def diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "ExperimentAuthoringContext",
    "diagnostic",
]
