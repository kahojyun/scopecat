"""Reusable behavior for interchangeable run repositories."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from scopecat.kernel.errors import CheckFailed, DataIntegrityError, NotFound
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.records.run_plan import (
    RunPlanDomainCapabilities,
    RunPlanDomainExecution,
    RunPlanExecutionOptions,
    RunPlanFusionOptions,
    RunPlanRecord,
)
from scopecat.runs.refs import CONFIG_PROFILE_SNAPSHOT_REF, MANIFEST_REF
from scopecat.runs.repository import RunRepository
from tests.testkit.authoring import load_config


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


def _config_source(content_hash: str) -> RunConfigSource:
    return RunConfigSource(
        selector="active",
        entry_id="config-entry",
        config_ref="configs/config-entry.json",
        content_hash=content_hash,
        registry_generation=1,
    )


def _structured_run_inputs(
    run_id: str,
    *,
    config: ConfigProfileSnapshot | None = None,
    plan_hash: str | None = None,
    source_hash: str | None = None,
) -> tuple[RunManifest, RunPlanRecord, ConfigProfileSnapshot]:
    selected_config = load_config() if config is None else config
    content_hash = config_content_hash(selected_config)
    plan = RunPlanRecord(
        config_content_hash=content_hash if plan_hash is None else plan_hash,
        backend_id="tests.execution.v1",
        execution_options=RunPlanExecutionOptions(
            requested=RunPlanFusionOptions(
                fusion="automatic",
                max_points_per_batch=None,
            ),
            resolved=RunPlanFusionOptions(
                fusion="automatic",
                max_points_per_batch=None,
            ),
        ),
        experiment_id="repository-contract",
        experiment_kind="contract",
        execution_units=[
            RunPlanDomainExecution(
                unit_id="domain",
                adapter_id="tests.domain",
                semantic_operation_id="execute",
                capabilities=RunPlanDomainCapabilities(max_points_per_batch=None),
                batches=[],
            )
        ],
        point_count=0,
    )
    manifest = RunManifest(
        run_id=run_id,
        lifecycle="accepted",
        config_source=_config_source(
            content_hash if source_hash is None else source_hash
        ),
    )
    return manifest, plan, selected_config


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

    def test_structured_run_inputs_bind_plan_source_and_snapshot_hashes(
        self,
        tmp_path: Path,
    ) -> None:
        repository = self.make_repository(tmp_path)
        manifest, plan, config = _structured_run_inputs("run-provenance-round-trip")

        repository.write_run_skeleton(
            manifest=manifest,
            request=None,
            plan=plan,
            config=config,
        )

        assert repository.read_run_plan(manifest.run_id) == plan
        assert repository.read_config_profile_snapshot(manifest.run_id) == config

    def test_structured_run_inputs_reject_hash_mismatch_before_publish(
        self,
        tmp_path: Path,
    ) -> None:
        repository = self.make_repository(tmp_path)
        mismatch = "sha256:" + "f" * 64
        cases = (
            _structured_run_inputs("run-plan-hash-mismatch", plan_hash=mismatch),
            _structured_run_inputs("run-source-hash-mismatch", source_hash=mismatch),
        )

        for manifest, plan, config in cases:
            with pytest.raises(DataIntegrityError) as captured:
                repository.write_run_skeleton(
                    manifest=manifest,
                    request=None,
                    plan=plan,
                    config=config,
                )
            assert captured.value.problems[0].code == ("run.config_provenance_mismatch")
            assert repository.ref_kind(manifest.run_id, MANIFEST_REF) == "missing"

    def test_structured_run_reads_detect_snapshot_drift(
        self,
        tmp_path: Path,
    ) -> None:
        repository = self.make_repository(tmp_path)
        manifest, plan, config = _structured_run_inputs("run-snapshot-drift")
        repository.write_run_skeleton(
            manifest=manifest,
            request=None,
            plan=plan,
            config=config,
        )
        drifted = config.model_copy(update={"id": "drifted-config"})
        repository.write_model(
            manifest.run_id,
            CONFIG_PROFILE_SNAPSHOT_REF,
            drifted,
        )

        for read in (
            repository.read_config_profile_snapshot,
            repository.read_run_plan,
        ):
            with pytest.raises(DataIntegrityError) as captured:
                read(manifest.run_id)
            assert captured.value.problems[0].code == ("run.config_provenance_mismatch")

    def test_direct_snapshot_run_is_protected_by_its_plan_hash(
        self,
        tmp_path: Path,
    ) -> None:
        repository = self.make_repository(tmp_path)
        manifest, plan, config = _structured_run_inputs("run-direct-snapshot")
        direct_manifest = manifest.model_copy(update={"config_source": None})
        repository.write_run_skeleton(
            manifest=direct_manifest,
            request=None,
            plan=plan,
            config=config,
        )
        repository.write_model(
            direct_manifest.run_id,
            CONFIG_PROFILE_SNAPSHOT_REF,
            config.model_copy(update={"id": "drifted-direct-snapshot"}),
        )

        with pytest.raises(DataIntegrityError) as captured:
            repository.read_config_profile_snapshot(direct_manifest.run_id)

        assert captured.value.problems[0].code == "run.config_provenance_mismatch"

    def test_config_read_remains_independent_for_capture_runs(
        self,
        tmp_path: Path,
    ) -> None:
        repository = self.make_repository(tmp_path)
        run_id = "capture-without-plan"
        config = load_config()
        repository.write_model(run_id, CONFIG_PROFILE_SNAPSHOT_REF, config)
        repository.write_manifest(RunManifest(run_id=run_id, lifecycle="accepted"))

        assert repository.read_config_profile_snapshot(run_id) == config

    def test_capture_config_read_still_checks_registry_source_hash(
        self,
        tmp_path: Path,
    ) -> None:
        repository = self.make_repository(tmp_path)
        run_id = "capture-with-mismatched-source"
        config = load_config()
        repository.write_model(run_id, CONFIG_PROFILE_SNAPSHOT_REF, config)
        repository.write_manifest(
            RunManifest(
                run_id=run_id,
                lifecycle="accepted",
                config_source=_config_source("sha256:" + "f" * 64),
            )
        )

        with pytest.raises(DataIntegrityError) as captured:
            repository.read_config_profile_snapshot(run_id)

        assert captured.value.problems[0].code == "run.config_provenance_mismatch"

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
