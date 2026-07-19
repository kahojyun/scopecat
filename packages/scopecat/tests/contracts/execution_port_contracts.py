"""Reusable behavioral contracts for interchangeable execution-side ports.

Concrete test classes inherit these mixins and provide only an implementation
factory.  Adapter-specific durability and corruption tests remain beside the
adapter; this module captures behavior every implementation must share.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scopecat.execution.ports.journal import (
    ExecutionJournal,
    ExecutionJournalError,
    PayloadEvidenceCommitter,
)
from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.records.execution_journal import (
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.records.parameter import Quantity


def _transition(run_id: str, ordinal: int) -> ExecutionTransition:
    return ExecutionTransition(
        run_id=run_id,
        operation_id=f"contract.operation.{ordinal}",
        stage="compute",
        effect="pure",
        state="completed",
        evidence={"ordinal": ordinal},
    )


def _transition_body(transition: ExecutionTransition) -> dict[str, object]:
    return transition.model_dump(
        mode="python",
        exclude={"sequence", "timestamp"},
    )


def _measurement_append(
    run_id: str,
    *,
    dataset_id: str = "raw-measurements",
    point_index: int = 0,
    value: float = 1.0,
) -> MeasurementDatasetAppend:
    logical_point_id = f"point-{point_index}"
    return MeasurementDatasetAppend(
        run_id=run_id,
        dataset_id=dataset_id,
        recording_contract_fingerprint=f"{dataset_id}.contract.v1",
        start_index=point_index,
        records=(
            MeasurementRecord(
                run_id=run_id,
                logical_point_id=logical_point_id,
                point_index=point_index,
                coordinates={},
                observables={"signal": Quantity(value=value, unit="ratio")},
            ),
        ),
    )


def _payload_evidence(
    run_id: str,
    *,
    operation_id: str = "contract.compute.0",
    content_hash: str = "sha256:payload-0",
) -> PayloadEvidence:
    return PayloadEvidence(
        run_id=run_id,
        operation_id=operation_id,
        point_index=0,
        payload_id="payload-0",
        schema_id="contract.payload.v1",
        content_hash=content_hash,
        fingerprint={"kind": "contract", "version": 1},
    )


class ExecutionJournalContract:
    """Shared contract for memory and durable execution journals."""

    def make_journal(self, tmp_path: Path, *, run_id: str) -> ExecutionJournal:
        raise NotImplementedError

    def read_entries(
        self,
        journal: ExecutionJournal,
    ) -> tuple[ExecutionTransition, ...]:
        raise NotImplementedError

    def test_append_assigns_sequence_and_preserves_transition(
        self,
        tmp_path: Path,
    ) -> None:
        run_id = "run-journal-contract"
        journal = self.make_journal(tmp_path, run_id=run_id)
        first_input = _transition(run_id, 0)
        second_input = _transition(run_id, 1)

        first = journal.append(first_input)
        second = journal.append(second_input)

        assert first_input.sequence is None
        assert second_input.sequence is None
        assert first.sequence == 0
        assert second.sequence == 1
        assert _transition_body(first) == _transition_body(first_input)
        assert _transition_body(second) == _transition_body(second_input)
        assert self.read_entries(journal) == (first, second)

    def test_concurrent_append_assigns_each_sequence_once(
        self,
        tmp_path: Path,
    ) -> None:
        run_id = "run-journal-concurrency-contract"
        journal = self.make_journal(tmp_path, run_id=run_id)

        def append_transition(ordinal: int) -> ExecutionTransition:
            return journal.append(_transition(run_id, ordinal))

        with ThreadPoolExecutor(max_workers=4) as executor:
            committed = tuple(
                executor.map(
                    append_transition,
                    range(12),
                )
            )

        committed_sequences: list[int] = []
        for entry in committed:
            assert entry.sequence is not None
            committed_sequences.append(entry.sequence)
        assert sorted(committed_sequences) == list(range(12))

        stored = self.read_entries(journal)
        stored_sequences: list[int] = []
        for entry in stored:
            assert entry.sequence is not None
            stored_sequences.append(entry.sequence)
        assert stored_sequences == list(range(12))
        assert {entry.operation_id for entry in stored} == {
            f"contract.operation.{ordinal}" for ordinal in range(12)
        }


class MeasurementDatasetWriterContract:
    """Shared idempotency contract for append-only measurement datasets."""

    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> MeasurementDatasetWriter:
        raise NotImplementedError

    def test_replay_returns_the_same_exact_receipt(self, tmp_path: Path) -> None:
        run_id = "run-measurement-committer-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        append = _measurement_append(run_id)

        first = committer.append(append)
        repeated = committer.append(append.model_copy(deep=True))

        assert repeated == first
        assert first == MeasurementDatasetReceipt(
            operation_id=append.operation_id,
            dataset_content_hash=append.content_hash,
            dataset_ref=first.dataset_ref,
        )

    def test_same_operation_rejects_different_content(self, tmp_path: Path) -> None:
        run_id = "run-measurement-conflict-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        append = _measurement_append(run_id)
        changed_record = append.records[0].model_copy(
            update={
                "observables": {"signal": Quantity(value=2.0, unit="ratio")},
            }
        )
        conflicting = append.model_copy(update={"records": (changed_record,)})
        assert conflicting.operation_id == append.operation_id
        assert conflicting.content_hash != append.content_hash

        committer.append(append)

        with pytest.raises(ExecutionJournalError):
            committer.append(conflicting)

    def test_distinct_dataset_operations_commit_independently(
        self,
        tmp_path: Path,
    ) -> None:
        run_id = "run-measurement-dataset-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        raw = _measurement_append(run_id)
        derived = raw.model_copy(
            update={
                "dataset_id": "derived-measurements",
                "recording_contract_fingerprint": "derived-measurements.contract.v1",
            }
        )

        raw_receipt = committer.append(raw)
        derived_receipt = committer.append(derived)

        assert raw.operation_id != derived.operation_id
        assert raw_receipt.operation_id == raw.operation_id
        assert derived_receipt.operation_id == derived.operation_id
        assert raw_receipt.dataset_ref != derived_receipt.dataset_ref

    def test_concurrent_replay_is_idempotent(self, tmp_path: Path) -> None:
        run_id = "run-measurement-concurrency-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        append = _measurement_append(run_id)

        def replay_append(_ordinal: int) -> MeasurementDatasetReceipt:
            return committer.append(append.model_copy(deep=True))

        with ThreadPoolExecutor(max_workers=4) as executor:
            receipts = tuple(
                executor.map(
                    replay_append,
                    range(8),
                )
            )

        assert len({receipt.model_dump_json() for receipt in receipts}) == 1

    def test_seal_is_idempotent_and_rejects_later_appends(self, tmp_path: Path) -> None:
        run_id = "run-measurement-seal-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        append = _measurement_append(run_id)
        committer.append(append)
        seal = MeasurementDatasetSeal(
            run_id=run_id,
            dataset_id=append.dataset_id,
            recording_contract_fingerprint=append.recording_contract_fingerprint,
            point_count=1,
            dataset_content_hash=measurement_dataset_content_hash(
                recording_contract_fingerprint=(append.recording_contract_fingerprint),
                append_content_hashes=(append.content_hash,),
            ),
        )

        first = committer.seal(seal)
        repeated = committer.seal(seal.model_copy(deep=True))

        assert repeated == first
        with pytest.raises(ExecutionJournalError):
            committer.append(_measurement_append(run_id, point_index=1))


class PayloadEvidenceCommitterContract:
    """Shared idempotency contract for structural payload evidence."""

    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> PayloadEvidenceCommitter:
        raise NotImplementedError

    def test_replay_returns_the_same_receipt(self, tmp_path: Path) -> None:
        run_id = "run-payload-committer-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        evidence = _payload_evidence(run_id)

        first = committer.commit(evidence)
        repeated = committer.commit(evidence.model_copy(deep=True))

        assert repeated == first
        assert first == CommittedPayloadEvidence(
            ref=first.ref,
            content_hash=evidence.content_hash,
        )
        assert first.ref

    def test_same_operation_rejects_different_evidence(self, tmp_path: Path) -> None:
        run_id = "run-payload-conflict-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        evidence = _payload_evidence(run_id)
        conflicting = evidence.model_copy(
            update={
                "content_hash": "sha256:different-payload",
                "fingerprint": {"kind": "contract", "version": 2},
            }
        )

        committer.commit(evidence)
        with pytest.raises(ExecutionJournalError):
            committer.commit(conflicting)

    def test_distinct_operations_commit_independently(self, tmp_path: Path) -> None:
        run_id = "run-payload-distinct-contract"
        committer = self.make_committer(tmp_path, run_id=run_id)
        first = committer.commit(_payload_evidence(run_id))
        second = committer.commit(
            _payload_evidence(
                run_id,
                operation_id="contract.compute.1",
                content_hash="sha256:payload-1",
            )
        )

        assert first.ref != second.ref
        assert first.content_hash != second.content_hash


__all__ = [
    "ExecutionJournalContract",
    "MeasurementDatasetWriterContract",
    "PayloadEvidenceCommitterContract",
]
