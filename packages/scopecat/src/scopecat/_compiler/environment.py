"""Validated, normalized configuration input for compiler passes."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat._parameter_resolution import resolve_config_parameters
from scopecat._relations import ParameterRelationData
from scopecat.diagnostics import Diagnostic
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.planning.validation import validate_config_profile
from scopecat.routing import RoutingView


@dataclass(frozen=True, slots=True)
class ValidatedConfigEnvironment:
    """One normalized config environment shared by every compile pass.

    Parameter normalization is deliberately performed once.  Downstream
    authoring, point binding, routing, preview, and execution planning all
    receive this same environment instead of independently resolving the
    accepted snapshot.
    """

    config: ConfigProfileSnapshot
    parameters: ParameterRelationData
    routing: RoutingView | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def valid(self) -> bool:
        return not any(
            diagnostic.severity in {"error", "blocker"}
            for diagnostic in self.diagnostics
        )


def validate_config_environment(
    config: ConfigProfileSnapshot,
) -> ValidatedConfigEnvironment:
    resolved = resolve_config_parameters(config)
    diagnostics = (
        *validate_config_profile(config, include_parameter_values=False),
        *resolved.diagnostics,
    )
    valid = not any(
        diagnostic.severity in {"error", "blocker"} for diagnostic in diagnostics
    )
    return ValidatedConfigEnvironment(
        config=config,
        parameters=resolved.data,
        routing=RoutingView.from_config(config) if valid else None,
        diagnostics=tuple(diagnostics),
    )


__all__ = ["ValidatedConfigEnvironment", "validate_config_environment"]
