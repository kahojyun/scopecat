"""Live bridge between a notebook-owned compiler and the daemon review GUI."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread
from typing import Self, cast

from scopecat.authoring.experiments import ExperimentInvocation
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.reviews import (
    ReviewCompilationResult,
    ReviewCompletionCommand,
    ReviewCoordinateSpec,
    ReviewCoordinateValue,
    ReviewInspectionView,
    ReviewPointView,
    ReviewSessionCreateCommand,
    ReviewSessionView,
    ReviewWorkItem,
)
from scopecat.execution.program import RunProgram
from scopecat.kernel.value_types import Bool, Entity, Float, Int, String
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.preview_models import ExperimentPreview, ExperimentPreviewPoint
from scopecat.program.point_domain import point_axis_size, point_axis_value

_PLANNED_VALUE_LIMIT = 256
_WORKER_POLL_SECONDS = 0.2
_HEARTBEAT_POLL_COUNT = 25


class ExperimentReviewHandle:
    """Keep a pure local compiler available to one browser review session."""

    def __init__(
        self,
        *,
        client: DaemonClient,
        program: RunProgram,
        invocation: ExperimentInvocation,
        session: ReviewSessionView,
        worker_id: str,
    ) -> None:
        self._client = client
        self._program = program
        self._invocation = invocation
        self._session = session
        self._worker_id = worker_id
        self._stop = Event()
        self._thread = Thread(
            target=self._serve,
            name=f"scopecat-review-{session.session_id}",
            daemon=True,
        )
        self._thread.start()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def id(self) -> str:
        return self._session.session_id

    @property
    def url(self) -> str:
        return f"{self._client.base_url}/#reviews/{self.id}"

    @property
    def session(self) -> ReviewSessionView:
        return self._client.get_review(self.id)

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._thread.join()
        self._client.close_review_worker(self.id, self._worker_id)

    def _serve(self) -> None:
        poll_count = 0
        while not self._stop.wait(_WORKER_POLL_SECONDS):
            item = self._client.claim_review_work(self.id, self._worker_id)
            if item is not None:
                self._complete(item)
            poll_count += 1
            if poll_count == _HEARTBEAT_POLL_COUNT:
                heartbeat = self._client.heartbeat_review_worker(
                    self.id,
                    self._worker_id,
                )
                if not heartbeat.active:
                    self._stop.set()
                    return
                poll_count = 0

    def _complete(self, item: ReviewWorkItem) -> None:
        try:
            preview = build_run_program_preview(
                self._program,
                invocation=self._invocation,
                point="first" if item.point_index is None else item.point_index,
                coordinates=item.coordinates,
                coordinate_mode=item.coordinate_mode,
            )
            result = _review_result(item.request_id, preview)
        except Exception as error:
            result = ReviewCompilationResult(
                request_id=item.request_id,
                completed_at=datetime.now(UTC),
                error=str(error),
            )
        self._client.complete_review_work(
            self.id,
            ReviewCompletionCommand(worker_id=self._worker_id, result=result),
        )


def create_experiment_review(
    *,
    client: DaemonClient,
    program: RunProgram,
    invocation: ExperimentInvocation,
    session_id: str,
    worker_id: str,
    title: str,
) -> ExperimentReviewHandle:
    """Publish one planned experiment and start its local compiler worker."""

    preview = build_run_program_preview(
        program,
        invocation=invocation,
    )
    command = ReviewSessionCreateCommand(
        session_id=session_id,
        worker_id=worker_id,
        title=title,
        experiment_id=program.experiment_id,
        experiment_kind=program.points.experiment_kind,
        coordinates=_coordinate_specs(program),
        planned_points=tuple(_review_point(point) for point in preview.points),
        planned_points_truncated=preview.points_truncated,
        initial_result=_review_result("initial", preview),
    )
    session = client.create_review(command)
    return ExperimentReviewHandle(
        client=client,
        program=program,
        invocation=invocation,
        session=session,
        worker_id=worker_id,
    )


def _coordinate_specs(program: RunProgram) -> tuple[ReviewCoordinateSpec, ...]:
    axes = {axis.id: axis for axis in program.points.contract.domain_axes}
    specs: list[ReviewCoordinateSpec] = []
    for column in program.points.contract.coordinate_columns:
        atom = column.value_type.atom
        axis = axes[column.id]
        size = point_axis_size(axis.source)
        values = tuple(
            cast("ReviewCoordinateValue", point_axis_value(axis.source, index))
            for index in range(min(size, _PLANNED_VALUE_LIMIT))
        )
        if isinstance(atom, Bool):
            kind = "bool"
            minimum = maximum = unit = choices = None
        elif isinstance(atom, Int):
            kind = "int"
            minimum, maximum = atom.minimum, atom.maximum
            unit = choices = None
        elif isinstance(atom, Float):
            kind = "float"
            minimum, maximum = atom.minimum, atom.maximum
            unit = choices = None
        elif isinstance(atom, String):
            kind = "string"
            minimum = maximum = unit = None
            choices = atom.choices
        elif isinstance(atom, QuantityType):
            kind = "quantity"
            minimum, maximum, unit = atom.minimum, atom.maximum, atom.unit
            choices = None
        elif isinstance(atom, Entity):
            kind = "entity"
            minimum = maximum = unit = choices = None
        else:
            raise TypeError(f"unsupported review coordinate type {type(atom).__name__}")
        specs.append(
            ReviewCoordinateSpec(
                id=column.id,
                kind=kind,
                unit=unit,
                minimum=minimum,
                maximum=maximum,
                choices=choices,
                planned_values=values,
                planned_values_truncated=size > len(values),
            )
        )
    return tuple(specs)


def _review_result(
    request_id: str,
    preview: ExperimentPreview,
) -> ReviewCompilationResult:
    return ReviewCompilationResult(
        request_id=request_id,
        completed_at=datetime.now(UTC),
        point=(
            None
            if preview.selected_point is None
            else _review_point(preview.selected_point)
        ),
        inspections=tuple(
            ReviewInspectionView(
                operation_id=inspection.operation_id,
                point_index=inspection.point_index,
                target_id=inspection.target_id,
                artifact_id=inspection.artifact_id,
                artifact_fingerprint=inspection.artifact_fingerprint,
                content=inspection.content,
            )
            for inspection in preview.domain_inspections
        ),
    )


def _review_point(selected: ExperimentPreviewPoint) -> ReviewPointView:
    return ReviewPointView(
        point_index=selected.point_index,
        coordinates=cast("dict[str, ReviewCoordinateValue]", selected.coordinates),
        proposal_fingerprint=selected.proposal_fingerprint,
        source=selected.source,
    )


__all__ = ["ExperimentReviewHandle", "create_experiment_review"]
