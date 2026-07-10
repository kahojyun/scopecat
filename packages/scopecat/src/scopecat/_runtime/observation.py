"""Transient runtime observation helpers."""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any

from scopecat._planning.compute_dependencies import (
    ComputeDependencySummary,
    summarize_compute_node_dependencies,
)
from scopecat._runtime.graph import RuntimeGraph
from scopecat.experiments import ComputeNodeSpec
from scopecat.instruments.events import (
    RuntimeEvent,
    RuntimeEventSink,
    RuntimePayloadObservation,
    RuntimePayloadObserver,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.run import RunStatus


def emit_event(event_sink: RuntimeEventSink | None, event: RuntimeEvent) -> None:
    if event_sink is None:
        return
    try:
        event_sink(event)
    except Exception:
        return


def emit_run_started(
    *,
    event_sink: RuntimeEventSink | None,
    run_id: str,
    experiment_id: str,
    graph: RuntimeGraph,
    instrument_ids: list[str],
) -> None:
    emit_event(
        event_sink,
        RuntimeEvent(
            kind="run_started",
            run_id=run_id,
            experiment_id=experiment_id,
            progress={"completed_points": 0, "total_points": graph.point_count},
            summary={
                "instrument_ids": instrument_ids,
                "record_ids": [record.id for record in graph.records],
            },
        ),
    )


def emit_run_finished(
    *,
    event_sink: RuntimeEventSink | None,
    run_id: str,
    experiment_id: str,
    status: RunStatus,
    completed_point_count: int,
    point_count: int,
    measurement_count: int,
    diagnostic_count: int,
    compute_evaluated_node_count: int,
    compute_reused_node_count: int,
    compute_payload_count: int,
) -> None:
    emit_event(
        event_sink,
        RuntimeEvent(
            kind="run_finished",
            run_id=run_id,
            experiment_id=experiment_id,
            progress={
                "completed_points": completed_point_count,
                "total_points": point_count,
            },
            summary={
                "status": status,
                "measurement_count": measurement_count,
                "diagnostic_count": diagnostic_count,
                "compute_evaluated_node_count": compute_evaluated_node_count,
                "compute_reused_node_count": compute_reused_node_count,
                "compute_payload_count": compute_payload_count,
            },
        ),
    )


def emit_compute_payload_events(
    *,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
    run_id: str,
    experiment_id: str,
    graph: RuntimeGraph,
    payloads: dict[str, CommandPayload],
    progress: dict[str, int],
) -> None:
    for payload in payloads.values():
        point_index = payload.metadata.get("point_index")
        node_id = payload.metadata.get("compute_node_id")
        node = (
            graph.compute_nodes_by_id.get(node_id) if isinstance(node_id, str) else None
        )
        dependencies = (
            graph.compute_dependencies_by_node.get(node_id, ComputeDependencySummary())
            if isinstance(node_id, str)
            else ComputeDependencySummary()
        )
        summary = command_payload_summary(
            payload,
            node=node,
            dependencies=dependencies,
        )
        emit_event(
            event_sink,
            RuntimeEvent(
                kind="compute_finished",
                run_id=run_id,
                experiment_id=experiment_id,
                point_index=point_index if isinstance(point_index, int) else None,
                progress=progress,
                summary=summary,
            ),
        )
        observe_payload(
            payload_observer,
            RuntimePayloadObservation(
                run_id=run_id,
                experiment_id=experiment_id,
                point_index=point_index if isinstance(point_index, int) else None,
                node_id=node_id if isinstance(node_id, str) else None,
                payload_id=payload.id,
                schema_id=payload.schema_id,
                compute_status=(
                    payload.metadata.get("compute_status")
                    if isinstance(payload.metadata.get("compute_status"), str)
                    else None
                ),
                payload=payload,
                summary=summary,
            ),
        )


def observe_payload(
    payload_observer: RuntimePayloadObserver | None,
    observation: RuntimePayloadObservation,
) -> None:
    if payload_observer is None:
        return
    try:
        payload_observer(observation)
    except Exception:
        return


def command_payload_summary(
    payload: CommandPayload,
    *,
    node: ComputeNodeSpec | None,
    dependencies: ComputeDependencySummary,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "payload_id": payload.id,
        "schema_id": payload.schema_id,
    }
    node_id = payload.metadata.get("compute_node_id")
    if isinstance(node_id, str):
        summary["node_id"] = node_id
    compute_status = payload.metadata.get("compute_status")
    if isinstance(compute_status, str):
        summary["compute_status"] = compute_status
    summary.update(python_payload_summary(payload.payload))
    if node is not None:
        dependencies = dependencies.merged(
            summarize_compute_node_dependencies(
                node,
                payload=payload.payload,
            )
        )
        dependency_map = dependencies.as_dict()
        if dependency_map:
            summary["dependencies"] = dependency_map
    return summary


def python_payload_summary(value: object) -> dict[str, Any]:
    if value is None:
        return {"type": "None"}
    summary: dict[str, Any] = {
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
    }
    if is_dataclass(value) and not isinstance(value, type):
        summary["fields"] = [field.name for field in dataclass_fields(value)]
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    if shape is not None:
        summary["shape"] = [int(dim) for dim in shape]
    if dtype is not None:
        summary["dtype"] = str(dtype)
    samples = getattr(value, "samples", None)
    if samples is not None:
        sample_shape = getattr(samples, "shape", None)
        sample_dtype = getattr(samples, "dtype", None)
        if sample_shape is not None:
            summary["sample_shape"] = [int(dim) for dim in sample_shape]
        if sample_dtype is not None:
            summary["sample_dtype"] = str(sample_dtype)
    channel_order = getattr(value, "channel_order", None)
    if channel_order is not None:
        summary["channel_order"] = [str(channel) for channel in channel_order]
        summary["channel_count"] = len(channel_order)
    entity_ids = getattr(value, "entity_ids", None)
    if entity_ids is not None:
        summary["entity_ids"] = [str(entity_id) for entity_id in entity_ids]
    compiler_id = getattr(value, "compiler_id", None)
    if isinstance(compiler_id, str):
        summary["compiler_id"] = compiler_id
    source_program_id = getattr(value, "source_program_id", None)
    if isinstance(source_program_id, str):
        summary["source_program_id"] = source_program_id
    return summary


__all__ = [
    "command_payload_summary",
    "emit_compute_payload_events",
    "emit_event",
    "emit_run_finished",
    "emit_run_started",
    "observe_payload",
    "python_payload_summary",
]
