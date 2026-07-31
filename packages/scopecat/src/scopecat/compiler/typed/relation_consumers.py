"""Semantic roles for scalar-expression uses in transient compiler programs."""

from __future__ import annotations

from enum import StrEnum


class ProgramRelationConsumerKind(StrEnum):
    """The executable program role that owns one scalar expression."""

    POINT_AXIS_CENTER = "point_axis_center"
    RESOURCE_ENTITY = "resource_entity"
    COMPUTE_INPUT = "compute_input"
    DOMAIN_EXECUTION_INPUT = "domain_execution_input"
    DOMAIN_COMPILER_INPUT = "domain_compiler_input"
    STATE_VALUE = "state_value"
    INVOCATION_ARGUMENT = "invocation_argument"
