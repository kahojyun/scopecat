"""Durable, point-canonical recording of projected measurement records."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, Protocol, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat._content_identity import model_wire_content_hash, stable_content_hash
from scopecat._execution.problems import problem_from_exception, runtime_problem
from scopecat.errors import MeasurementRecordingError
from scopecat.execution_journal import ExecutionJournal, ExecutionTransition
from scopecat.measurement_projection import ProjectedMeasurementRecords
from scopecat.models.measurement import MeasurementRecord
from scopecat.problems import Problem, ProblemCategory, ProblemPhase

_MAX_RECORD_REF_LENGTH = 512
_DURABLE_RECORD_REF = re.compile(
    r"[A-Za-z][A-Za-z0-9._-]*/(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*"
    r"[A-Za-z0-9][A-Za-z0-9._-]*"
)
_FORBIDDEN_RECORD_REF_NAMESPACES = frozenset({"data", "inline", "javascript"})


class MeasurementRecordChunk(BaseModel):
    """One idempotently writable projected record with complete logical identity."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.measurement_record_chunk.v1"] = (
        "scopecat.measurement_record_chunk.v1"
    )
    run_id: str
    dataset_id: str
    recording_contract_fingerprint: str
    logical_point_id: str
    point_index: int = Field(ge=0)
    record: MeasurementRecord

    @field_validator(
        "run_id",
        "dataset_id",
        "recording_contract_fingerprint",
        "logical_point_id",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            msg = "measurement record chunk identity fields must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("point_index", mode="before")
    @classmethod
    def validate_point_index(cls, value: object) -> object:
        if isinstance(value, bool):
            msg = "measurement record chunk point index must be an integer"
            raise ValueError(msg)
        return value

    @field_validator("record", mode="before")
    @classmethod
    def snapshot_record(cls, value: object) -> MeasurementRecord:
        if not isinstance(value, MeasurementRecord):
            return MeasurementRecord.model_validate(value)
        return value.model_copy(deep=True)

    @model_validator(mode="after")
    def validate_record_identity(self) -> MeasurementRecordChunk:
        if self.record.run_id != self.run_id:
            msg = "measurement record chunk and record run ids must match"
            raise ValueError(msg)
        if self.record.point_index != self.point_index:
            msg = "measurement record chunk and record point indices must match"
            raise ValueError(msg)
        if self.record.metadata.get("logical_point_id") != self.logical_point_id:
            msg = "measurement record chunk logical point does not match its record"
            raise ValueError(msg)
        return self

    @property
    def operation_id(self) -> str:
        digest = stable_content_hash(
            {
                "schema": "scopecat.measurement_record_operation.v1",
                "run_id": self.run_id,
                "dataset_id": self.dataset_id,
                "recording_contract_fingerprint": (self.recording_contract_fingerprint),
                "logical_point_id": self.logical_point_id,
                "point_index": self.point_index,
            }
        )
        return f"measurement-record:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class MeasurementRecordReceipt(BaseModel):
    """Durable committer evidence for one exact measurement record chunk."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.measurement_record_receipt.v1"] = (
        "scopecat.measurement_record_receipt.v1"
    )
    operation_id: str
    chunk_content_hash: str
    record_ref: str

    @field_validator("operation_id", "chunk_content_hash")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            msg = "measurement record receipt fields must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("record_ref")
    @classmethod
    def validate_record_ref(cls, value: str) -> str:
        if not value or len(value) > _MAX_RECORD_REF_LENGTH:
            msg = "measurement record receipt ref has an invalid length"
            raise ValueError(msg)
        namespace, separator, _key = value.partition("/")
        if (
            not separator
            or namespace.lower() in _FORBIDDEN_RECORD_REF_NAMESPACES
            or _DURABLE_RECORD_REF.fullmatch(value) is None
        ):
            msg = (
                "measurement record receipt ref must be a safe namespaced "
                "relative durable locator"
            )
            raise ValueError(msg)
        return value

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class MeasurementRecordCommitter(Protocol):
    """Idempotently commit one chunk by its deterministic operation identity."""

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt: ...


class MemoryMeasurementRecordCommitter:
    """Deterministic in-memory committer for tests and embedded execution."""

    def __init__(self) -> None:
        self._chunks: dict[str, MeasurementRecordChunk] = {}
        self._receipts: dict[str, MeasurementRecordReceipt] = {}
        self._lock = Lock()

    @property
    def chunks(self) -> tuple[MeasurementRecordChunk, ...]:
        with self._lock:
            return tuple(_normalize_chunk(chunk) for chunk in self._chunks.values())

    @property
    def receipts(self) -> tuple[MeasurementRecordReceipt, ...]:
        with self._lock:
            return tuple(
                _normalize_receipt(receipt) for receipt in self._receipts.values()
            )

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt:
        durable = _normalize_chunk(chunk)
        with self._lock:
            existing = self._chunks.get(durable.operation_id)
            if existing is not None and existing.content_hash != durable.content_hash:
                msg = (
                    f"measurement record operation {durable.operation_id} already "
                    "has different content"
                )
                raise ValueError(msg)
            if existing is None:
                receipt = MeasurementRecordReceipt(
                    operation_id=durable.operation_id,
                    chunk_content_hash=durable.content_hash,
                    record_ref=(
                        "memory/measurement-records/"
                        f"{durable.operation_id.removeprefix('measurement-record:')}"
                        ".json"
                    ),
                )
                self._chunks[durable.operation_id] = durable
                self._receipts[durable.operation_id] = receipt
            return MeasurementRecordReceipt.model_validate(
                self._receipts[durable.operation_id].model_dump(mode="json")
            )


@dataclass(frozen=True, slots=True)
class CommittedProjectedMeasurementRecords:
    """Trusted internal result for a completely committed projected batch."""

    projected: ProjectedMeasurementRecords = field(repr=False)
    receipts: tuple[MeasurementRecordReceipt, ...]


def commit_projected_measurement_records(
    projected: ProjectedMeasurementRecords,
    committer: MeasurementRecordCommitter,
    journal: ExecutionJournal,
    *,
    attempt: int = 1,
) -> CommittedProjectedMeasurementRecords:
    """Commit a canonical projected batch with journaled point-level evidence."""

    if type(attempt) is not int or attempt < 1:
        msg = "measurement recording attempt must be a positive integer"
        raise ValueError(msg)
    if not callable(getattr(committer, "commit", None)):
        msg = "measurement recording requires a MeasurementRecordCommitter"
        raise TypeError(msg)
    if not callable(getattr(journal, "append", None)):
        msg = "measurement recording requires an ExecutionJournal"
        raise TypeError(msg)

    # Construct every durable chunk before the first journal or committer
    # effect. No later point can reveal a structural batch error.
    chunks = _chunks_for_projected(projected)
    operation_ids = tuple(chunk.operation_id for chunk in chunks)
    if len(operation_ids) != len(set(operation_ids)):
        msg = "projected measurement records require unique operation identities"
        raise ValueError(msg)
    prepared_chunks = tuple((chunk, chunk.content_hash) for chunk in chunks)
    committed: list[MeasurementRecordReceipt] = []

    for chunk, expected_chunk_hash in prepared_chunks:
        started = _recording_transition(
            chunk,
            attempt=attempt,
            state="started",
            evidence=_chunk_evidence(chunk, expected_chunk_hash),
        )
        try:
            _commit_transition(journal, started)
        except Exception as error:
            problem = _exception_problem(
                chunk,
                code="measurement_record_intent_persistence_failed",
                message="failed to persist measurement record intent before writing",
                error=error,
                category=ProblemCategory.STORAGE,
            )
            raise _recording_error(
                chunk,
                attempt=attempt,
                problems=(problem,),
                committed=committed,
                pending_receipt=None,
                write_may_have_completed=False,
                reconciliation=(
                    "retry after the recording intent can be durably committed"
                ),
            ) from error

        try:
            raw_receipt = committer.commit(chunk)
        except Exception as error:
            problem = _exception_problem(
                chunk,
                code="measurement_record_commit_raised",
                message="measurement record committer raised while writing the chunk",
                error=error,
                category=ProblemCategory.EXTERNAL_FAILURE,
            )
            problems = _append_unknown_best_effort(
                journal,
                started,
                chunk=chunk,
                problems=(problem,),
                pending_receipt=None,
            )
            raise _recording_error(
                chunk,
                attempt=attempt,
                problems=problems,
                committed=committed,
                pending_receipt=None,
                write_may_have_completed=True,
                reconciliation=(
                    "replay the same deterministic operation and chunk; the "
                    "committer must reconcile it idempotently"
                ),
            ) from error
        except BaseException:
            problem = runtime_problem(
                "measurement_record_commit_interrupted",
                "measurement record commit was interrupted",
                run_id=chunk.run_id,
                operation_id=chunk.operation_id,
                point_index=chunk.point_index,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.INTERRUPTED,
            )
            _append_unknown_best_effort(
                journal,
                started,
                chunk=chunk,
                problems=(problem,),
                pending_receipt=None,
            )
            raise

        pending_receipt: MeasurementRecordReceipt | None = None
        try:
            receipt = _normalize_receipt(raw_receipt)
            pending_receipt = receipt
            _require_receipt_correlation(
                chunk,
                receipt,
                expected_chunk_hash=expected_chunk_hash,
                committed_record_refs={item.record_ref for item in committed},
            )
        except Exception as error:
            problem = runtime_problem(
                "measurement_record_receipt_invalid",
                "measurement record committer returned an invalid receipt",
                run_id=chunk.run_id,
                operation_id=chunk.operation_id,
                point_index=chunk.point_index,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.PROVIDER_CONTRACT,
                details={
                    "error_type": f"{type(error).__module__}.{type(error).__qualname__}"
                },
            )
            problems = _append_unknown_best_effort(
                journal,
                started,
                chunk=chunk,
                problems=(problem,),
                pending_receipt=pending_receipt,
            )
            raise _recording_error(
                chunk,
                attempt=attempt,
                problems=problems,
                committed=committed,
                pending_receipt=pending_receipt,
                write_may_have_completed=True,
                reconciliation=(
                    "replay the same deterministic operation and require a receipt "
                    "matching the exact chunk"
                ),
            ) from error

        completed = _recording_transition(
            chunk,
            attempt=attempt,
            state="completed",
            evidence={
                **_chunk_evidence(chunk, expected_chunk_hash),
                "receipt": receipt.model_dump(mode="json"),
                "receipt_content_hash": receipt.content_hash,
            },
        )
        try:
            _commit_transition(journal, completed)
        except Exception as error:
            problem = _exception_problem(
                chunk,
                code="measurement_record_receipt_persistence_failed",
                message="failed to persist measurement record receipt after writing",
                error=error,
                category=ProblemCategory.STORAGE,
            )
            raise _recording_error(
                chunk,
                attempt=attempt,
                problems=(problem,),
                committed=committed,
                pending_receipt=receipt,
                write_may_have_completed=True,
                reconciliation=(
                    "replay or inspect the same deterministic operation using the "
                    "pending receipt before advancing"
                ),
            ) from error
        committed.append(receipt)

    return CommittedProjectedMeasurementRecords(
        projected,
        tuple(committed),
    )


def _chunks_for_projected(
    projected: ProjectedMeasurementRecords,
) -> tuple[MeasurementRecordChunk, ...]:
    # Keep the dependency one-way at import time: errors can describe receipt
    # evidence without importing this runtime module.
    from scopecat.measurement_projection import require_projected_measurement_records

    selected = require_projected_measurement_records(projected)
    records = selected.records
    if not records:
        return ()
    schema = selected.schema
    if schema is None:
        msg = "projected measurement records require a dataset schema before writing"
        raise ValueError(msg)
    points = selected.selection.projection.linked_points.point_domain.points
    return tuple(
        MeasurementRecordChunk(
            run_id=selected.run_id,
            dataset_id=schema.dataset_id,
            recording_contract_fingerprint=(selected.recording_contract_fingerprint),
            logical_point_id=point.logical_id.value,
            point_index=point.logical_ordinal,
            record=record,
        )
        for point, record in zip(points, records, strict=True)
    )


def _recording_transition(
    chunk: MeasurementRecordChunk,
    *,
    attempt: int,
    state: Literal["started", "completed", "unknown"],
    evidence: dict[str, JsonValue],
    problems: Sequence[Problem] = (),
) -> ExecutionTransition:
    return ExecutionTransition(
        run_id=chunk.run_id,
        operation_id=chunk.operation_id,
        stage="record_measurement",
        effect="persistence",
        state=state,
        attempt=attempt,
        point_index=chunk.point_index,
        problems=tuple(problems),
        evidence=evidence,
    )


def _chunk_evidence(
    chunk: MeasurementRecordChunk,
    content_hash: str,
) -> dict[str, JsonValue]:
    return {
        "dataset_id": chunk.dataset_id,
        "recording_contract_fingerprint": chunk.recording_contract_fingerprint,
        "logical_point_id": chunk.logical_point_id,
        "chunk_content_hash": content_hash,
    }


def _commit_transition(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
) -> ExecutionTransition:
    expected = transition.model_dump(
        mode="json",
        exclude={"sequence", "timestamp"},
    )
    committed = journal.append(transition)
    if not isinstance(cast("object", committed), ExecutionTransition):
        msg = "execution journal returned no committed measurement transition"
        raise TypeError(msg)
    normalized = ExecutionTransition.model_validate(committed.model_dump(mode="json"))
    if normalized.sequence is None:
        msg = "measurement recording requires a journal-assigned durable sequence"
        raise ValueError(msg)
    actual = normalized.model_dump(
        mode="json",
        exclude={"sequence", "timestamp"},
    )
    if actual != expected:
        msg = "execution journal changed measurement transition identity or evidence"
        raise ValueError(msg)
    return normalized


def _require_receipt_correlation(
    chunk: MeasurementRecordChunk,
    receipt: MeasurementRecordReceipt,
    *,
    expected_chunk_hash: str | None = None,
    committed_record_refs: set[str] | None = None,
) -> None:
    expected_hash = (
        chunk.content_hash if expected_chunk_hash is None else expected_chunk_hash
    )
    if receipt.operation_id != chunk.operation_id:
        msg = "measurement record receipt operation id does not match its chunk"
        raise ValueError(msg)
    if receipt.chunk_content_hash != expected_hash:
        msg = "measurement record receipt content hash does not match its chunk"
        raise ValueError(msg)
    if (
        committed_record_refs is not None
        and receipt.record_ref in committed_record_refs
    ):
        msg = "measurement record receipt reuses an already committed durable ref"
        raise ValueError(msg)


def _append_unknown_best_effort(
    journal: ExecutionJournal,
    started: ExecutionTransition,
    *,
    chunk: MeasurementRecordChunk,
    problems: tuple[Problem, ...],
    pending_receipt: MeasurementRecordReceipt | None,
) -> tuple[Problem, ...]:
    evidence = dict(started.evidence)
    if pending_receipt is not None:
        evidence.update(
            {
                "pending_receipt": pending_receipt.model_dump(mode="json"),
                "pending_receipt_content_hash": pending_receipt.content_hash,
            }
        )
    unknown = _recording_transition(
        chunk,
        attempt=started.attempt,
        state="unknown",
        evidence=evidence,
        problems=problems,
    )
    try:
        _commit_transition(journal, unknown)
    except Exception as error:
        persistence_problem = _exception_problem(
            chunk,
            code="measurement_record_unknown_persistence_failed",
            message="failed to persist uncertain measurement record outcome",
            error=error,
            category=ProblemCategory.STORAGE,
        )
        return (*problems, persistence_problem)
    return problems


def _exception_problem(
    chunk: MeasurementRecordChunk,
    *,
    code: str,
    message: str,
    error: Exception,
    category: ProblemCategory,
) -> Problem:
    return problem_from_exception(
        code,
        message,
        run_id=chunk.run_id,
        operation_id=chunk.operation_id,
        point_index=chunk.point_index,
        error=error,
        phase=ProblemPhase.PERSISTENCE,
        category=category,
    )


def _recording_error(
    chunk: MeasurementRecordChunk,
    *,
    attempt: int,
    problems: Sequence[Problem],
    committed: Sequence[MeasurementRecordReceipt],
    pending_receipt: MeasurementRecordReceipt | None,
    write_may_have_completed: bool,
    reconciliation: str,
) -> MeasurementRecordingError:
    return MeasurementRecordingError(
        problems,
        run_id=chunk.run_id,
        dataset_id=chunk.dataset_id,
        recording_contract_fingerprint=chunk.recording_contract_fingerprint,
        operation_id=chunk.operation_id,
        attempt=attempt,
        logical_point_id=chunk.logical_point_id,
        point_index=chunk.point_index,
        committed_prefix=tuple(committed),
        pending_receipt=pending_receipt,
        write_may_have_completed=write_may_have_completed,
        reconciliation=reconciliation,
    )


def _normalize_chunk(value: object) -> MeasurementRecordChunk:
    if not isinstance(value, MeasurementRecordChunk):
        msg = "measurement record committer requires MeasurementRecordChunk"
        raise TypeError(msg)
    return MeasurementRecordChunk.model_validate(value.model_dump(mode="python"))


def _normalize_receipt(value: object) -> MeasurementRecordReceipt:
    if not isinstance(value, MeasurementRecordReceipt):
        msg = "measurement record committer must return MeasurementRecordReceipt"
        raise TypeError(msg)
    return MeasurementRecordReceipt.model_validate(value.model_dump(mode="json"))


__all__ = [
    "CommittedProjectedMeasurementRecords",
    "MeasurementRecordChunk",
    "MeasurementRecordCommitter",
    "MeasurementRecordReceipt",
    "MemoryMeasurementRecordCommitter",
    "commit_projected_measurement_records",
]
