"""Semantic roles for proof-owning fields in transient compiler programs."""

from __future__ import annotations

from enum import StrEnum


class ProgramRelationConsumerKind(StrEnum):
    """The executable program role that owns one verified relation plan."""

    POINT_DOMAIN_ROWS = "point_domain_rows"
    PARAMETER_OVERLAY_KEY = "parameter_overlay_key"
    PARAMETER_OVERLAY_VALUE = "parameter_overlay_value"
    ROUTE_ENTITY = "route_entity"
    COMPUTE_INPUT = "compute_input"
    DOMAIN_EXECUTION_INPUT = "domain_execution_input"
    ACTION_VALUE = "action_value"
    STATE_RESOURCE = "state_resource"
    STATE_VALUE = "state_value"
    STATE_ROUTE_ENTITY = "state_route_entity"
    STATE_RELATION = "state_relation"
