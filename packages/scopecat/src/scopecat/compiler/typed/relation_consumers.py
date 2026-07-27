"""Semantic roles for verified relation uses in transient compiler programs."""

from __future__ import annotations

from enum import StrEnum


class ProgramRelationConsumerKind(StrEnum):
    """The executable program role that owns one verified relation plan."""

    POINT_AXIS_CENTER = "point_axis_center"
    PARAMETER_OVERLAY_KEY = "parameter_overlay_key"
    PARAMETER_OVERLAY_VALUE = "parameter_overlay_value"
    RESOURCE_ENTITY = "resource_entity"
    COMPUTE_INPUT = "compute_input"
    DOMAIN_EXECUTION_INPUT = "domain_execution_input"
    DOMAIN_COMPILER_INPUT = "domain_compiler_input"
    STATE_VALUE = "state_value"
