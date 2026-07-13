"""Reusable behavior for interchangeable run repositories."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from scopecat.kernel.errors import CheckFailed, DataIntegrityError, NotFound
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.repository import RunRepository


class _ContractRecord(BaseModel):
    message: str
    value: float = 0.0


def _manifest(run_id: str, day: int) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        created_at=datetime(2026, 1, day, tzinfo=UTC),
        lifecycle="terminal",
        outcome=RunOutcome(
            run_id=run_id,
            result="succeeded",
            certainty="known",
            termination_reason="completed",
        ),
    )


class RunRepositoryContract:
    """Logical refs, error semantics, and idempotency shared by adapters."""

    def make_repository(self, tmp_path: Path) -> RunRepository:
        raise NotImplementedError

    def test_round_trips_all_portable_content(self, tmp_path: Path) -> None:
        repository = self.make_repository(tmp_path)
        run_id = "run-repository-contract"
        manifest = _manifest(run_id, 1)
        record = _ContractRecord(message="record", value=float("inf"))

        repository.write_manifest(manifest)
        repository.write_model(run_id, "records/model.json", record)
        repository.write_text(run_id, "artifacts/note.txt", "note")
        repository.write_bytes(run_id, "artifacts/blob.bin", b"\x00\xff")
        repository.write_jsonl(
            run_id,
            "records/events.jsonl",
            [_ContractRecord(message="one"), _ContractRecord(message="two")],
        )

        assert repository.read_manifest(run_id) == manifest
        assert (
            repository.read_model(run_id, "records/model.json", _ContractRecord)
            == record
        )
        assert repository.read_text(run_id, "artifacts/note.txt") == "note\n"
        assert repository.read_bytes(run_id, "artifacts/blob.bin") == b"\x00\xff"
        assert repository.read_jsonl(
            run_id,
            "records/events.jsonl",
            _ContractRecord,
        ) == [_ContractRecord(message="one"), _ContractRecord(message="two")]
        assert repository.ref_kind(run_id, "records/model.json") == "file"
        assert repository.ref_kind(run_id, "records/missing.json") == "missing"

    def test_lists_runs_by_creation_time(self, tmp_path: Path) -> None:
        repository = self.make_repository(tmp_path)
        repository.write_manifest(_manifest("run-later", 2))
        repository.write_manifest(_manifest("run-earlier", 1))

        assert [manifest.run_id for manifest in repository.list_runs()] == [
            "run-earlier",
            "run-later",
        ]

    def test_if_absent_is_atomic_and_preserves_original(self, tmp_path: Path) -> None:
        repository = self.make_repository(tmp_path)
        run_id = "run-if-absent-contract"
        ref = "records/immutable.json"
        original = _ContractRecord(message="original")

        assert repository.write_model_if_absent(run_id, ref, original)
        assert not repository.write_model_if_absent(
            run_id,
            ref,
            _ContractRecord(message="different"),
        )
        assert repository.read_model(run_id, ref, _ContractRecord) == original

    def test_missing_run_and_ref_have_stable_errors(self, tmp_path: Path) -> None:
        repository = self.make_repository(tmp_path)

        with pytest.raises(NotFound) as missing_run:
            repository.read_manifest("run-missing")
        assert missing_run.value.problems[0].code == "run.not_found"

        with pytest.raises(DataIntegrityError) as missing_ref:
            repository.read_text("run-missing", "records/missing.json")
        assert missing_ref.value.problems[0].code == "run.ref_missing"

    @pytest.mark.parametrize("ref", ("../outside.json", "/outside.json"))
    def test_rejects_refs_outside_run_namespace(
        self,
        tmp_path: Path,
        ref: str,
    ) -> None:
        repository = self.make_repository(tmp_path)

        with pytest.raises(CheckFailed) as captured:
            repository.write_text("run-contract", ref, "escape")
        assert captured.value.problems[0].code == "run.ref_path_escape"


__all__ = ["RunRepositoryContract"]
