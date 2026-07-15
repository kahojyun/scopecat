"""Best-effort observation of transient and durable execution transitions.

Runtime events are lossy projections for notebooks and user interfaces, not an
audit log or replay protocol. Events derived from committed journal entries
retain their sequence; transient progress has none. Observer failure is logged
and cannot change run semantics. The execution journal remains the authority
for externally relevant effects and recovery.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import SupportsInt, cast

from pydantic import JsonValue

from scopecat.execution.observation import (
    RunFinishedEvent,
    RunStartedEvent,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimePayloadObservation,
    RuntimePayloadObserver,
    RuntimeProgress,
    RuntimeTransitionEvent,
)
from scopecat.records.artifact import CommandPayload
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.run import RunOutcome

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


class RuntimeTransitionProjector:
    """Project operation transitions into a lossy, non-authoritative stream.

    Callers decide separately whether a transition belongs in the durable
    effect ledger.  Durable transitions should be observed only after their
    journal append succeeds; transient progress may be observed directly and
    therefore has no journal sequence.
    """

    def __init__(
        self,
        *,
        event_sink: RuntimeEventSink | None,
        experiment_id: str,
        point_count: int,
    ) -> None:
        self._event_sink = event_sink
        self._experiment_id = experiment_id
        self._point_count = point_count
        self._completed_points: set[int] = set()

    def observe(self, transition: ExecutionTransition) -> None:
        """Emit one transition without changing execution semantics."""

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
    point_index = payload.point_index
    operation_id = payload.operation_id
    semantic_operation_id = payload.semantic_operation_id
    implementation_id = payload.implementation_id
    compute_status = payload.compute_status
    try:
        observer(
            RuntimePayloadObservation(
                run_id=run_id,
                experiment_id=experiment_id,
                point_index=point_index,
                semantic_operation_id=semantic_operation_id,
                payload_id=payload.id,
                schema_id=payload.schema_id,
                compute_status=compute_status,
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
    shape = cast("Sequence[SupportsInt] | None", getattr(value, "shape", None))
    dtype = cast("object | None", getattr(value, "dtype", None))
    if shape is not None:
        shape_summary: list[JsonValue] = [int(dimension) for dimension in shape]
        summary["shape"] = shape_summary
    if dtype is not None:
        summary["dtype"] = str(dtype)
    samples = cast("object | None", getattr(value, "samples", None))
    if samples is not None:
        sample_shape = cast(
            "Sequence[SupportsInt] | None",
            getattr(samples, "shape", None),
        )
        sample_dtype = cast("object | None", getattr(samples, "dtype", None))
        if sample_shape is not None:
            sample_shape_summary: list[JsonValue] = [
                int(dimension) for dimension in sample_shape
            ]
            summary["sample_shape"] = sample_shape_summary
        if sample_dtype is not None:
            summary["sample_dtype"] = str(sample_dtype)
    channel_order = cast(
        "Sequence[object] | None",
        getattr(value, "channel_order", None),
    )
    if channel_order is not None:
        channel_summary: list[JsonValue] = [str(channel) for channel in channel_order]
        summary["channel_order"] = channel_summary
        summary["channel_count"] = len(channel_order)
    entity_ids = cast(
        "Sequence[object] | None",
        getattr(value, "entity_ids", None),
    )
    if entity_ids is not None:
        entity_summary: list[JsonValue] = [str(entity_id) for entity_id in entity_ids]
        summary["entity_ids"] = entity_summary
    for attribute in ("compiler_id", "source_program_id"):
        selected = cast("object | None", getattr(value, attribute, None))
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
    "RuntimeTransitionProjector",
    "emit_run_finished",
    "emit_run_started",
    "observe_payload",
    "payload_summary",
]
