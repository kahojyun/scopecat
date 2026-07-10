"""Resolve state-demanded compute payloads against their producers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from scopecat._compute_result import ComputeResultRef
from scopecat._planning.diagnostics import planning_diagnostic
from scopecat._planning.state import StateRecord
from scopecat.value_types import Payload, Scalar, ValueType


class ComputePayloadProducer(Protocol):
    """Structural producer contract needed for payload resolution."""

    id: str
    output_type: ValueType


@dataclass(frozen=True)
class ComputePayloadSchemaResolution:
    """Resolved producer schemas and demanded results that cannot be produced."""

    schema_ids: dict[str, str]
    unavailable_node_ids: frozenset[str]
    diagnostics: tuple[dict[str, Any], ...]


def resolve_compute_payload_schemas(
    state_records: Sequence[StateRecord],
    compute_nodes: Sequence[ComputePayloadProducer],
) -> ComputePayloadSchemaResolution:
    """Join payload demands in state to compute-node output declarations."""

    producers = {node.id: node for node in compute_nodes}
    demanded_node_ids = dict.fromkeys(
        record.value.node_id
        for record in state_records
        if isinstance(record.value, ComputeResultRef)
    )
    schema_ids: dict[str, str] = {}
    unavailable_node_ids: set[str] = set()
    diagnostics: list[dict[str, Any]] = []

    for node_id in demanded_node_ids:
        producer = producers.get(node_id)
        if producer is None:
            unavailable_node_ids.add(node_id)
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "compute_payload_unknown_node",
                    f"compute payload references unknown node {node_id!r}",
                    "desired_state.value.node_id",
                )
            )
            continue

        output_type = producer.output_type
        if not isinstance(output_type, Scalar) or not isinstance(
            output_type.atom, Payload
        ):
            unavailable_node_ids.add(node_id)
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "compute_payload_output_type_invalid",
                    (
                        f"compute node {node_id!r} must use a scalar payload "
                        "output type before its result can be bound to state"
                    ),
                    f"compute_nodes.{node_id}.output_type",
                )
            )
            continue

        schema_ids[node_id] = output_type.atom.schema_id

    return ComputePayloadSchemaResolution(
        schema_ids=schema_ids,
        unavailable_node_ids=frozenset(unavailable_node_ids),
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "ComputePayloadProducer",
    "ComputePayloadSchemaResolution",
    "resolve_compute_payload_schemas",
]
