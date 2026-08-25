from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from scopecat.config.documents import load_config_snapshot_document
from scopecat.control.models import RunPlanSummary, RunResourceRequirement
from scopecat.daemon.wire import (
    RunSubmission,
    SampleCreateCommand,
    SampleReviseCommand,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run_request import RunRequest
from scopecat.records.sample import (
    SampleRelation,
    SampleRevisionDraft,
    SampleSelector,
)

from scopecat_server import LocalDaemonRuntime

_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-snapshot.json"
)


def _config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(_FIXTURE)


def _submission(sample_id: str) -> RunSubmission:
    return RunSubmission(
        submission_id="sample-run-submission",
        config=_config(),
        request=RunRequest(
            experiment_id="sample-scan",
            samples=(SampleSelector(sample_id=sample_id, context_id="cooldown-1"),),
        ),
        plan=RunPlanSummary(
            experiment_id="sample-scan",
            experiment_kind="sample-scan",
            point_plan_fingerprint="a" * 64,
            measurement_contract_fingerprint="b" * 64,
            point_count=1,
            initial_point_count=1,
            point_limit=1,
            run_resource_requirements=(
                RunResourceRequirement(id="source-0", kind="instrument"),
            ),
        ),
    )


def test_sample_revision_and_run_binding_survive_restart(tmp_path: Path) -> None:
    with (
        LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        parent_response = transport.post(
            "/api/v1/samples",
            json=SampleCreateCommand(
                operation_id="create:wafer-1",
                sample_id="wafer-1",
                kind="wafer",
                actor="operator",
                content=SampleRevisionDraft(
                    display_name="Wafer 1",
                    tags=("lot-a",),
                ),
            ).model_dump(mode="json"),
        )
        assert parent_response.status_code == 201

        create_response = transport.post(
            "/api/v1/samples",
            json=SampleCreateCommand(
                operation_id="create:die-1",
                sample_id="die-1",
                kind="die",
                actor="operator",
                content=SampleRevisionDraft(
                    display_name="Die 1",
                    relations=(SampleRelation(kind="cut_from", sample_id="wafer-1"),),
                ),
            ).model_dump(mode="json"),
        )
        assert create_response.status_code == 201

        revise_response = transport.post(
            "/api/v1/samples/die-1/revisions",
            json=SampleReviseCommand(
                operation_id="revise:die-1:2",
                expected_revision=1,
                actor="operator",
                note="mounted for cooldown",
                content=SampleRevisionDraft(
                    display_name="Die 1 / device A",
                    status="mounted",
                    tags=("lot-a", "device-a"),
                    relations=(SampleRelation(kind="cut_from", sample_id="wafer-1"),),
                ),
            ).model_dump(mode="json"),
        )
        assert revise_response.status_code == 200
        assert revise_response.json()["revision"]["revision"] == 2

        admission = runtime.application.submit_run(_submission("die-1"))
        binding = admission.snapshot.samples[0]
        assert binding.sample_id == "die-1"
        assert binding.revision == 2
        assert binding.display_name == "Die 1 / device A"
        assert binding.context_id == "cooldown-1"

        page_response = transport.get("/api/v1/samples")
        assert page_response.status_code == 200
        die_summary = next(
            item
            for item in page_response.json()["items"]
            if item["record"]["id"] == "die-1"
        )
        assert die_summary["run_count"] == 1

        detail_response = transport.get("/api/v1/samples/die-1")
        assert detail_response.status_code == 200
        assert [
            revision["revision"] for revision in detail_response.json()["revisions"]
        ] == [2, 1]

        run_id = admission.run_id

    with LocalDaemonRuntime(tmp_path) as restarted:
        sample = restarted.application.samples.get("die-1")
        snapshot = restarted.application.runs.get_run(run_id).snapshot

    assert sample.record.active_revision == 2
    assert sample.run_count == 1
    assert snapshot.samples == (binding,)
