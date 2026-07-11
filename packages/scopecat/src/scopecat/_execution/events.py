"""Best-effort observation adapters for durable execution transitions."""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any

from scopecat._execution.journal import ExecutionJournal, ExecutionJournalEntry
from scopecat.instruments.events import (
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventSink,
    RuntimePayloadObservation,
    RuntimePayloadObserver,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.run import RunStatus


class ObservedExecutionJournal:
    """Decorate the required journal with a lossy UI event stream."""

    def __init__(
        self,
        journal: ExecutionJournal,
        *,
        event_sink: RuntimeEventSink | None,
        experiment_id: str,
        point_count: int,
    ) -> None:
        self._journal = journal
        self._event_sink = event_sink
        self._experiment_id = experiment_id
        self._point_count = point_count
        self._completed_points: set[int] = set()

    def append(self, entry: ExecutionJournalEntry) -> ExecutionJournalEntry:
        committed = self._journal.append(entry)
        self._observe(committed)
        return committed

    def _observe(self, entry: ExecutionJournalEntry) -> None:
        event_kind: RuntimeEventKind | None = None
        if entry.stage == "point" and entry.state == "started":
            event_kind = "point_started"
        elif entry.stage == "point" and entry.state != "started":
            if entry.state == "completed" and entry.point_index is not None:
                self._completed_points.add(entry.point_index)
            event_kind = "point_finished"
        elif entry.stage == "compute" and entry.state == "completed":
            event_kind = "compute_finished"
        elif entry.stage == "apply_state" and entry.state == "completed":
            event_kind = "state_applied"
        elif entry.stage == "apply_state" and entry.state != "started":
            event_kind = "state_reconcile_finished"
        elif entry.stage == "collect" and entry.state == "started":
            event_kind = "collect_started"
        elif entry.stage == "collect" and entry.state != "started":
            event_kind = "collect_finished"
        elif entry.stage == "commit_point" and entry.state == "completed":
            event_kind = "record_emitted"
        if event_kind is None:
            return
        _emit(
            self._event_sink,
            RuntimeEvent(
                kind=event_kind,
                run_id=entry.run_id,
                experiment_id=self._experiment_id,
                point_index=entry.point_index,
                instrument_id=entry.instrument_id,
                progress={
                    "completed_points": len(self._completed_points),
                    "total_points": self._point_count,
                },
                summary={
                    **entry.summary,
                    "operation_id": entry.operation_id,
                    "operation_state": entry.state,
                },
            ),
        )


def emit_run_started(
    *,
    event_sink: RuntimeEventSink | None,
    run_id: str,
    experiment_id: str,
    point_count: int,
    instrument_ids: list[str],
    output_ids: list[str],
) -> None:
    _emit(
        event_sink,
        RuntimeEvent(
            kind="run_started",
            run_id=run_id,
            experiment_id=experiment_id,
            progress={"completed_points": 0, "total_points": point_count},
            summary={
                "instrument_ids": instrument_ids,
                "record_ids": output_ids,
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
    _emit(
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


def observe_payload(
    *,
    observer: RuntimePayloadObserver | None,
    run_id: str,
    experiment_id: str,
    payload: CommandPayload,
) -> None:
    if observer is None:
        return
    point_index = payload.metadata.get("point_index")
    operation_id = payload.metadata.get("operation_id")
    kernel_id = payload.metadata.get("kernel_id")
    compute_status = payload.metadata.get("compute_status")
    try:
        observer(
            RuntimePayloadObservation(
                run_id=run_id,
                experiment_id=experiment_id,
                point_index=point_index if isinstance(point_index, int) else None,
                node_id=kernel_id if isinstance(kernel_id, str) else None,
                payload_id=payload.id,
                schema_id=payload.schema_id,
                compute_status=(
                    compute_status if isinstance(compute_status, str) else None
                ),
                payload=payload,
                summary={
                    "payload_id": payload.id,
                    "schema_id": payload.schema_id,
                    **payload_summary(payload.payload),
                    **({"node_id": kernel_id} if isinstance(kernel_id, str) else {}),
                    **(
                        {"operation_id": operation_id}
                        if isinstance(operation_id, str)
                        else {}
                    ),
                },
            )
        )
    except Exception:
        return


def payload_summary(value: object) -> dict[str, Any]:
    """Return bounded, JSON-safe structural metadata for an opaque payload."""

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
        summary["shape"] = [int(dimension) for dimension in shape]
    if dtype is not None:
        summary["dtype"] = str(dtype)
    samples = getattr(value, "samples", None)
    if samples is not None:
        sample_shape = getattr(samples, "shape", None)
        sample_dtype = getattr(samples, "dtype", None)
        if sample_shape is not None:
            summary["sample_shape"] = [int(dimension) for dimension in sample_shape]
        if sample_dtype is not None:
            summary["sample_dtype"] = str(sample_dtype)
    channel_order = getattr(value, "channel_order", None)
    if channel_order is not None:
        summary["channel_order"] = [str(channel) for channel in channel_order]
        summary["channel_count"] = len(channel_order)
    entity_ids = getattr(value, "entity_ids", None)
    if entity_ids is not None:
        summary["entity_ids"] = [str(entity_id) for entity_id in entity_ids]
    for attribute in ("compiler_id", "source_program_id"):
        selected = getattr(value, attribute, None)
        if isinstance(selected, str):
            summary[attribute] = selected
    return summary


def _emit(sink: RuntimeEventSink | None, event: RuntimeEvent) -> None:
    if sink is None:
        return
    try:
        sink(event)
    except Exception:
        return


__all__ = [
    "ObservedExecutionJournal",
    "emit_run_finished",
    "emit_run_started",
    "observe_payload",
    "payload_summary",
]
