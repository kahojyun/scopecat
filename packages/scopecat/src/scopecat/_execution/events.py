"""Best-effort observation adapters for durable execution transitions."""

from __future__ import annotations

import logging
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass

from pydantic import JsonValue

from scopecat._execution.journal import ExecutionJournal, ExecutionTransition
from scopecat.models.artifact import CommandPayload
from scopecat.models.run import RunOutcome
from scopecat.runtime import (
    RunFinishedEvent,
    RunStartedEvent,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimePayloadObservation,
    RuntimePayloadObserver,
    RuntimeProgress,
    RuntimeTransitionEvent,
)

logger = logging.getLogger(__name__)

_OBSERVATION_METRIC_KEYS = frozenset(
    {
        "channel_count",
        "channel_order",
        "changed_field_count",
        "compute_evaluated_node_count",
        "compute_payload_count",
        "compute_reused_node_count",
        "compute_step_count",
        "compute_status",
        "compiler_id",
        "dependencies",
        "dtype",
        "entity_ids",
        "field_count",
        "fields",
        "implementation_id",
        "measurement_count",
        "observable_ids",
        "payload_count",
        "payload_id",
        "receipt_status",
        "request_count",
        "sample_dtype",
        "sample_shape",
        "schema_id",
        "semantic_operation_id",
        "shape",
        "skipped_field_count",
        "source_program_id",
        "state_command_count",
        "type",
        "value_count",
    }
)


class ObservedExecutionJournal:
    """Decorate the required journal with a lossy, non-authoritative stream."""

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

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        committed = self._journal.append(entry)
        self._observe(committed)
        return committed

    def _observe(self, transition: ExecutionTransition) -> None:
        if (
            transition.stage == "point"
            and transition.state == "completed"
            and transition.point_index is not None
        ):
            self._completed_points.add(transition.point_index)
        _emit(
            self._event_sink,
            RuntimeTransitionEvent(
                run_id=transition.run_id,
                experiment_id=self._experiment_id,
                sequence=transition.sequence,
                occurred_at=transition.timestamp,
                operation_id=transition.operation_id,
                stage=transition.stage,
                effect=transition.effect,
                state=transition.state,
                point_index=transition.point_index,
                instrument_id=transition.instrument_id,
                progress=RuntimeProgress(
                    completed_points=len(self._completed_points),
                    total_points=self._point_count,
                ),
                metrics=_observation_metrics(transition.evidence),
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
        RunStartedEvent(
            run_id=run_id,
            experiment_id=experiment_id,
            progress=RuntimeProgress(completed_points=0, total_points=point_count),
            instrument_ids=tuple(instrument_ids),
            record_ids=tuple(output_ids),
        ),
    )


def emit_run_finished(
    *,
    event_sink: RuntimeEventSink | None,
    run_id: str,
    experiment_id: str,
    outcome: RunOutcome,
    completed_point_count: int,
    point_count: int,
    measurement_count: int,
    problem_count: int,
    compute_evaluated_node_count: int,
    compute_reused_node_count: int,
    compute_payload_count: int,
) -> None:
    _emit(
        event_sink,
        RunFinishedEvent(
            run_id=run_id,
            experiment_id=experiment_id,
            progress=RuntimeProgress(
                completed_points=completed_point_count,
                total_points=point_count,
            ),
            result=outcome.result,
            certainty=outcome.certainty,
            termination_reason=outcome.termination_reason,
            measurement_count=measurement_count,
            problem_count=problem_count,
            compute_evaluated_node_count=compute_evaluated_node_count,
            compute_reused_node_count=compute_reused_node_count,
            compute_payload_count=compute_payload_count,
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
    semantic_operation_id = payload.metadata.get("semantic_operation_id")
    implementation_id = payload.metadata.get("implementation_id")
    compute_status = payload.metadata.get("compute_status")
    try:
        observer(
            RuntimePayloadObservation(
                run_id=run_id,
                experiment_id=experiment_id,
                point_index=point_index if isinstance(point_index, int) else None,
                semantic_operation_id=(
                    semantic_operation_id
                    if isinstance(semantic_operation_id, str)
                    else None
                ),
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
                    **(
                        {"semantic_operation_id": semantic_operation_id}
                        if isinstance(semantic_operation_id, str)
                        else {}
                    ),
                    **(
                        {"implementation_id": implementation_id}
                        if isinstance(implementation_id, str)
                        else {}
                    ),
                    **(
                        {"operation_id": operation_id}
                        if isinstance(operation_id, str)
                        else {}
                    ),
                },
            )
        )
    except BaseException as error:
        _log_observer_failure(
            error,
            adapter="payload_observer",
            run_id=run_id,
        )


def payload_summary(value: object) -> dict[str, JsonValue]:
    """Return bounded, JSON-safe structural metadata for an opaque payload."""

    if value is None:
        return {"type": "None"}
    summary: dict[str, JsonValue] = {
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


def _observation_metrics(evidence: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        key: value for key, value in evidence.items() if key in _OBSERVATION_METRIC_KEYS
    }


def _emit(sink: RuntimeEventSink | None, event: RuntimeEvent) -> None:
    if sink is None:
        return
    try:
        sink(event)
    except BaseException as error:
        _log_observer_failure(error, adapter="event_sink", run_id=event.run_id)


def _log_observer_failure(
    error: BaseException,
    *,
    adapter: str,
    run_id: str,
) -> None:
    logger.error(
        "runtime observation adapter failed",
        extra={"adapter": adapter, "run_id": run_id},
        exc_info=(type(error), error, error.__traceback__),
    )


__all__ = [
    "ObservedExecutionJournal",
    "emit_run_finished",
    "emit_run_started",
    "observe_payload",
    "payload_summary",
]
