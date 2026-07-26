"""Normalized configuration input consumed by compiler passes."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.records.config import ConfigProfileSnapshot


@dataclass(frozen=True, slots=True)
class ConfigEnvironment:
    """Accepted config facts shared by every compile pass."""

    config: ConfigProfileSnapshot
    parameters: ParameterRelationData
