from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast, get_type_hints

import pytest
from pydantic import ValidationError

from scopecat.errors import MeasurementRecordingError
from scopecat.execution_journal import ExecutionTransition, MemoryExecutionJournal
from scopecat.measurement_projection import (
    ProjectedMeasurementRecords,
    bind_measurement_projection,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurement_recording import (
    CommittedProjectedMeasurementRecords,
    MeasurementRecordChunk,
    MeasurementRecordReceipt,
    MemoryMeasurementRecordCommitter,
    commit_projected_measurement_records,
)
from scopecat.measurement_values import (
    assemble_measurement_values,
    seal_measurement_value_fragment,
    select_measurement_value_assembly,
)
from scopecat.models.parameter import Quantity
from tests.test_measurement_projection import _assembled_for_all_uses
from tests.test_measurement_value_assembly import _candidates, _definition, _scenario


def _projected(*, run_id: str = "recording-run") -> ProjectedMeasurementRecords:
    scenario, selected, assembled = _assembled_for_all_uses()
    bound = bind_measurement_projection(
        select_measurement_projection(scenario.linked_points),
        selected,
    )
    return project_measurement_records(bound, assembled, run_id=run_id)


def _zero_projected() -> ProjectedMeasurementRecords:
    scenario = _scenario(point_values=(), use_count=1)
    selected = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=(scenario.uses[0].id,),
        fragment_defs=(_definition("zero", scenario.uses),),
    )
    fragment = seal_measurement_value_fragment(
        selected,
        "zero",
        _candidates(scenario, scenario.uses),
    )
    values = assemble_measurement_values(selected, (fragment,))
    bound = bind_measurement_projection(
        select_measurement_projection(scenario.linked_points),
        selected,
    )
    return project_measurement_records(bound, values, run_id="zero-recording-run")


def _empty_projection() -> ProjectedMeasurementRecords:
    scenario = _scenario(point_values=(0.0, 1.0), use_count=0)
    selected = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=(),
        fragment_defs=(),
    )
    values = assemble_measurement_values(selected, ())
    bound = bind_measurement_projection(
        select_measurement_projection(scenario.linked_points),
        selected,
    )
    return project_measurement_records(bound, values, run_id="empty-recording-run")


def test_recording_commits_canonical_points_with_strict_journal_evidence() -> None:
    projected = _projected()
    committer = MemoryMeasurementRecordCommitter()
    journal = MemoryExecutionJournal()

    committed = commit_projected_measurement_records(
        projected,
        committer,
        journal,
        attempt=2,
    )

    assert isinstance(committed, CommittedProjectedMeasurementRecords)
    assert committed.projected is projected
    assert committed.receipts == committer.receipts
    assert len(committed.receipts) == len(projected.records) == 2
    assert [chunk.point_index for chunk in committer.chunks] == [0, 1]
    assert [chunk.logical_point_id for chunk in committer.chunks] == [
        record.metadata["logical_point_id"] for record in projected.records
    ]
    assert [
        (entry.stage, entry.effect, entry.state, entry.attempt, entry.point_index)
        for entry in journal.entries
    ] == [
        ("record_measurement", "persistence", "started", 2, 0),
        ("record_measurement", "persistence", "completed", 2, 0),
        ("record_measurement", "persistence", "started", 2, 1),
        ("record_measurement", "persistence", "completed", 2, 1),
    ]
    for chunk, receipt, started, completed in zip(
        committer.chunks,
        committed.receipts,
        journal.entries[::2],
        journal.entries[1::2],
        strict=True,
    ):
        assert started.operation_id == completed.operation_id == chunk.operation_id
        assert receipt.operation_id == chunk.operation_id
        assert receipt.chunk_content_hash == chunk.content_hash
        assert started.evidence["chunk_content_hash"] == chunk.content_hash
        assert completed.evidence["receipt"] == receipt.model_dump(mode="json")
        assert receipt.record_ref.endswith(
            f"{chunk.operation_id.removeprefix('measurement-record:')}.json"
        )


def test_chunk_operation_identity_is_stable_but_content_detects_conflict() -> None:
    projected = _projected()
    schema = projected.schema
    assert schema is not None
    record = projected.records[0]
    logical_point_id = cast("str", record.metadata["logical_point_id"])
    chunk = MeasurementRecordChunk(
        run_id=projected.run_id,
        dataset_id=schema.dataset_id,
        recording_contract_fingerprint=projected.recording_contract_fingerprint,
        logical_point_id=logical_point_id,
        point_index=record.point_index,
        record=record,
    )
    observables = dict(record.observables)
    observables["primary"] = Quantity(value=99.0, unit="ratio")
    changed = MeasurementRecordChunk(
        run_id=chunk.run_id,
        dataset_id=chunk.dataset_id,
        recording_contract_fingerprint=chunk.recording_contract_fingerprint,
        logical_point_id=chunk.logical_point_id,
        point_index=chunk.point_index,
        record=record.model_copy(update={"observables": observables}),
    )

    assert chunk.operation_id == changed.operation_id
    assert chunk.content_hash != changed.content_hash
    committer = MemoryMeasurementRecordCommitter()
    committer.commit(chunk)
    with pytest.raises(ValueError, match="different content"):
        committer.commit(changed)


@pytest.mark.parametrize(
    "record_ref",
    [
        "data:application/octet-stream;base64,cmF3X2ZyYW1l",
        "inline/raw_frame",
        'memory/measurement-records/{"raw_frame":"embedded"}.json',
        "memory/measurement-records/frame.json?raw_frame=embedded",
        "memory/measurement-records/%7Braw_frame%7D.json",
        "memory/measurement-records/raw frame.json",
        "memory/measurement-records/raw\nframe.json",
        "memory/measurement-records/" + "x" * 512,
    ],
)
def test_receipt_rejects_inline_or_payload_bearing_record_refs(
    record_ref: str,
) -> None:
    with pytest.raises(ValidationError, match="receipt ref"):
        MeasurementRecordReceipt(
            operation_id="measurement-record:operation",
            chunk_content_hash="chunk-hash",
            record_ref=record_ref,
        )


@pytest.mark.parametrize(
    "record_ref",
    [
        "memory/measurement-records/0123456789abcdef.json",
        "execution/measurements/0123456789abcdef.json",
        "lab-record-store/run-42/point-0001.json",
    ],
)
def test_receipt_accepts_supported_durable_record_refs(record_ref: str) -> None:
    assert (
        MeasurementRecordReceipt(
            operation_id="measurement-record:operation",
            chunk_content_hash="chunk-hash",
            record_ref=record_ref,
        ).record_ref
        == record_ref
    )


@pytest.mark.parametrize("projected", [_zero_projected(), _empty_projection()])
def test_zero_or_empty_recording_has_no_write_or_transition(
    projected: ProjectedMeasurementRecords,
) -> None:
    committer = MemoryMeasurementRecordCommitter()
    journal = MemoryExecutionJournal()

    committed = commit_projected_measurement_records(projected, committer, journal)

    assert committed.receipts == ()
    assert committer.chunks == ()
    assert journal.entries == ()


@pytest.mark.parametrize("projected", [_zero_projected(), _empty_projection()])
def test_zero_or_empty_recording_still_rejects_fractional_attempt(
    projected: ProjectedMeasurementRecords,
) -> None:
    committer = MemoryMeasurementRecordCommitter()
    journal = MemoryExecutionJournal()

    with pytest.raises(ValueError, match="positive integer"):
        commit_projected_measurement_records(
            projected,
            committer,
            journal,
            attempt=cast("int", 1.5),
        )

    assert committer.chunks == ()
    assert journal.entries == ()


@dataclass
class _NoSequenceJournal:
    append_calls: int = 0

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        self.append_calls += 1
        return entry.model_copy(deep=True)


@dataclass
class _MutatingJournal:
    committed: MemoryExecutionJournal = field(default_factory=MemoryExecutionJournal)

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        return self.committed.append(
            entry.model_copy(update={"evidence": {"changed": True}})
        )


@pytest.mark.parametrize("journal", [_NoSequenceJournal(), _MutatingJournal()])
def test_invalid_journal_is_rejected_before_record_write(journal: object) -> None:
    committer = MemoryMeasurementRecordCommitter()

    with pytest.raises(MeasurementRecordingError) as captured:
        commit_projected_measurement_records(
            _projected(),
            committer,
            cast("MemoryExecutionJournal", journal),
        )

    error = captured.value
    assert error.committed_prefix == ()
    assert error.pending_receipt is None
    assert error.write_may_have_completed is False
    assert error.retry == "safe"
    assert committer.chunks == ()


@dataclass
class _RaiseSecondCommitter:
    committed: MemoryMeasurementRecordCommitter = field(
        default_factory=MemoryMeasurementRecordCommitter
    )
    calls: int = 0

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("injected measurement record failure")
        return self.committed.commit(chunk)


def test_commit_exception_exposes_committed_prefix_and_uncertain_write() -> None:
    committer = _RaiseSecondCommitter()
    journal = MemoryExecutionJournal()

    with pytest.raises(MeasurementRecordingError) as captured:
        commit_projected_measurement_records(_projected(), committer, journal)

    error = captured.value
    assert len(error.committed_prefix) == 1
    assert error.pending_receipt is None
    assert error.write_may_have_completed is True
    assert error.retry == "safe"
    assert committer.calls == 2
    assert [(entry.point_index, entry.state) for entry in journal.entries] == [
        (0, "started"),
        (0, "completed"),
        (1, "started"),
        (1, "unknown"),
    ]


@dataclass
class _InvalidReceiptCommitter:
    committed: MemoryMeasurementRecordCommitter = field(
        default_factory=MemoryMeasurementRecordCommitter
    )

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt:
        receipt = self.committed.commit(chunk)
        return receipt.model_copy(update={"operation_id": "foreign-operation"})


def test_invalid_receipt_remains_pending_and_never_enters_committed_prefix() -> None:
    committer = _InvalidReceiptCommitter()
    journal = MemoryExecutionJournal()

    with pytest.raises(MeasurementRecordingError) as captured:
        commit_projected_measurement_records(_projected(), committer, journal)

    error = captured.value
    assert error.committed_prefix == ()
    assert error.pending_receipt is not None
    assert error.pending_receipt.operation_id == "foreign-operation"
    assert error.write_may_have_completed is True
    assert len(committer.committed.chunks) == 1
    assert [entry.state for entry in journal.entries] == ["started", "unknown"]


@dataclass
class _ReusedRecordRefCommitter:
    committed: MemoryMeasurementRecordCommitter = field(
        default_factory=MemoryMeasurementRecordCommitter
    )
    first_ref: str | None = None

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt:
        receipt = self.committed.commit(chunk)
        if self.first_ref is None:
            self.first_ref = receipt.record_ref
            return receipt
        return receipt.model_copy(update={"record_ref": self.first_ref})


def test_batch_rejects_reused_record_ref_as_an_invalid_receipt() -> None:
    committer = _ReusedRecordRefCommitter()
    journal = MemoryExecutionJournal()

    with pytest.raises(MeasurementRecordingError) as captured:
        commit_projected_measurement_records(_projected(), committer, journal)

    error = captured.value
    assert len(error.committed_prefix) == 1
    assert error.pending_receipt is not None
    assert error.pending_receipt.record_ref == error.committed_prefix[0].record_ref
    assert error.write_may_have_completed is True
    assert [entry.state for entry in journal.entries] == [
        "started",
        "completed",
        "started",
        "unknown",
    ]


@dataclass
class _FailOnAppendJournal:
    fail_call: int
    committed: MemoryExecutionJournal = field(default_factory=MemoryExecutionJournal)
    calls: int = 0

    @property
    def entries(self) -> tuple[ExecutionTransition, ...]:
        return self.committed.entries

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        self.calls += 1
        if self.calls == self.fail_call:
            raise RuntimeError("injected measurement journal failure")
        return self.committed.append(entry)


def test_post_write_journal_failure_exposes_prefix_and_pending_receipt() -> None:
    committer = MemoryMeasurementRecordCommitter()
    journal = _FailOnAppendJournal(fail_call=4)

    with pytest.raises(MeasurementRecordingError) as captured:
        commit_projected_measurement_records(_projected(), committer, journal)

    error = captured.value
    assert len(error.committed_prefix) == 1
    assert error.pending_receipt is not None
    assert error.pending_receipt == committer.receipts[1]
    assert error.write_may_have_completed is True
    assert error.point_index == 1
    assert len(committer.chunks) == 2
    assert [(entry.point_index, entry.state) for entry in journal.entries] == [
        (0, "started"),
        (0, "completed"),
        (1, "started"),
    ]


def test_safe_replay_is_idempotent_and_uses_the_same_operation_ids() -> None:
    projected = _projected()
    committer = MemoryMeasurementRecordCommitter()
    journal = MemoryExecutionJournal()

    first = commit_projected_measurement_records(projected, committer, journal)
    repeated = commit_projected_measurement_records(
        projected,
        committer,
        journal,
        attempt=2,
    )

    assert repeated.receipts == first.receipts
    assert len(committer.chunks) == 2
    assert [entry.operation_id for entry in journal.entries[:4]] == [
        entry.operation_id for entry in journal.entries[4:]
    ]
    assert [entry.attempt for entry in journal.entries[4:]] == [2, 2, 2, 2]


def test_measurement_recording_error_annotation_is_runtime_resolvable() -> None:
    assert get_type_hints(MeasurementRecordingError.__init__)
