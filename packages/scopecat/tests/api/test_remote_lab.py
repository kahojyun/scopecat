# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import cast

import httpx2
import pyarrow as pa
import pytest
from pydantic import BaseModel
from scopecat_testkit.measurement_models import signal_point_schema, signal_record
from scopecat_testkit.planning import plan_configured_experiment
from scopecat_testkit.signal_instruments import TestSignalInstrumentProvider
from scopecat_testkit.workflow_fixtures import (
    load_config,
    load_invocation,
)

import scopecat.api._runner as runner_module
from scopecat.api._runner import _DaemonRunner
from scopecat.api.analysis import AnalysisContext
from scopecat.api.lab import LabClient
from scopecat.api.run import RunHandle
from scopecat.config.drafts import ConfigDraft
from scopecat.config.inventory import InstrumentInventoryRekey
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
    ManualConfigDraftRegistrySource,
)
from scopecat.config.resolution import config_revision_entry_id
from scopecat.control.models import RunResourceRequirement
from scopecat.daemon.client import (
    DaemonClient,
    DaemonConflictError,
    DaemonUnavailableError,
)
from scopecat.daemon.execution import ExecutorLeaseLostError
from scopecat.daemon.points import RunPointPlanView
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigRegistryView,
    RunAdmissionView,
    RunControlView,
    RunDetail,
    RunPlanView,
)
from scopecat.daemon.wire import (
    ConfigActivationReceipt,
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
    DirectConfigRevisionSource,
    ExecutorLease,
    InstrumentContractCatalogRequest,
    InstrumentInventoryMigrationCommand,
    InstrumentInventoryMigrationReceipt,
    ManualConfigDraftRevisionSource,
    RunAdmission,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.execution.program import RunProgram
from scopecat.execution.services import ExecutionSession
from scopecat.kernel.errors import RunCancelled
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.measurements.results import MeasurementDataset
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.service import PlannedRun
from scopecat.planning.system import ExperimentSystem
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
    instrument_bindings,
)
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementScalar
from scopecat.records.run import ConfigRegistryRunConfigSource, RunManifest
from scopecat.runs.data import RunMeasurementDatasetResult
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments import InstrumentProviderContext

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_remote_run_uses_full_dataset_batches_and_projected_arrow_pages() -> None:
    schema = signal_point_schema(size=3)
    dataset_entry = RunContentEntry(
        role="dataset",
        id="raw-measurements",
        kind="measurement_dataset",
        content_hash="measurement-content",
        schema=schema.model_dump(mode="json"),
        metadata={"experiment": "remote-page-test"},
    )
    manifest = RunManifest(
        run_id="run-batches",
        config_content_hash=config_content_hash(load_config()),
        contents=(dataset_entry,),
    )
    detail = RunDetail(
        control=RunControlView(
            sequence=1,
            admission=RunAdmissionView(
                run_id=manifest.run_id,
                plan=RunPlanView(
                    experiment_id="remote-batches",
                    experiment_kind="test",
                    point_count=3,
                    initial_point_count=3,
                    point_limit=3,
                ),
                admitted_at=_NOW,
            ),
            state="closed",
            updated_at=_NOW,
            completed_point_count=3,
            point_plan=RunPointPlanView(
                run_id=manifest.run_id,
                initial_point_count=3,
                accepted_point_count=3,
                point_limit=3,
                decision_count=0,
                optimizer_attempt_count=0,
                operator_request_count=0,
                plan_closed=True,
                stop_reason="static point plan",
            ),
        ),
        manifest=manifest,
    )
    records = tuple(
        signal_record(point_index=index).model_copy(update={"run_id": manifest.run_id})
        for index in range(3)
    )
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == "/api/v1/runs/run-batches":
            return _model(detail)
        if request.url.path == ("/api/v1/runs/run-batches/datasets/raw-measurements"):
            return _model(
                RunMeasurementDatasetResult(
                    dataset_entry=dataset_entry,
                    dataset=MeasurementDataset(
                        dataset_schema=schema,
                        records=records,
                        metadata=dataset_entry.metadata,
                    ),
                )
            )
        if request.url.path == "/api/v1/runs/run-batches/measurements/arrow":
            query = json.loads(request.content)
            offset = query["offset"]
            items = records[offset : offset + query["limit"]]
            table = pa.table(
                {
                    "point_index": [record.point_index for record in items],
                    "logical_point_id": [record.logical_point_id for record in items],
                    "signal": [
                        cast("MeasurementScalar", record.observables["signal"]).value
                        for record in items
                    ],
                    "signal__unavailable_reason": [None] * len(items),
                }
            )
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
            next_offset = offset + len(items)
            return httpx2.Response(
                200,
                content=sink.getvalue().to_pybytes(),
                headers={
                    "X-Scopecat-Snapshot-Size": str(len(records)),
                    **(
                        {"X-Scopecat-Next-Offset": str(next_offset)}
                        if next_offset < len(records)
                        else {}
                    ),
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    lab = LabClient(_client(handler))
    run = RunHandle(session=lab, id=manifest.run_id)

    reader = cast(
        "Iterator[object]",
        AnalysisContext(run=run)
        .measurements()
        .project({"signal": "signal"}, diagnostics="reason")
        .to_record_batch_reader(batch_size=2),
    )
    assert [request.url.path for request in requests] == [
        "/api/v1/runs/run-batches",
        "/api/v1/runs/run-batches/measurements/arrow",
    ]

    assert len(list(reader)) == 2
    assert [request.url.path for request in requests] == [
        "/api/v1/runs/run-batches",
        "/api/v1/runs/run-batches/measurements/arrow",
        "/api/v1/runs/run-batches/measurements/arrow",
    ]
    queries = [
        json.loads(request.content)
        for request in requests
        if request.url.path.endswith("/measurements/arrow")
    ]
    assert [query["offset"] for query in queries] == [0, 2]
    assert [query["snapshot_size"] for query in queries] == [None, 3]
    assert all(
        query["columns"] == [{"name": "signal", "variable_id": "signal"}]
        for query in queries
    )


def test_lab_preview_and_run_are_direct_prepare_shortcuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation = load_invocation()
    preview_result = object()
    run_result = object()
    prepared_calls: list[tuple[object, object]] = []
    forwarded: list[tuple[str, dict[str, object]]] = []

    class Prepared:
        def preview(self, **kwargs: object) -> object:
            forwarded.append(("preview", kwargs))
            return preview_result

        def run(self, **kwargs: object) -> object:
            forwarded.append(("run", kwargs))
            return run_result

    def prepare(
        _lab: LabClient,
        experiment: object,
        *,
        config: object = None,
    ) -> Prepared:
        prepared_calls.append((experiment, config))
        return Prepared()

    monkeypatch.setattr(LabClient, "prepare", prepare)
    lab = object.__new__(LabClient)

    assert lab.preview(invocation, config="active", name="preview") is preview_result
    assert lab.run(invocation, config="candidate", name="run") is run_result
    assert prepared_calls == [(invocation, "active"), (invocation, "candidate")]
    assert forwarded == [
        (
            "preview",
            {
                "point": "first",
                "coordinates": None,
                "coordinate_mode": "exact",
                "name": "preview",
                "tags": (),
                "description": None,
                "metadata": None,
                "operator": None,
            },
        ),
        (
            "run",
            {
                "name": "run",
                "tags": (),
                "description": None,
                "metadata": None,
                "operator": None,
            },
        ),
    ]


def test_execute_submits_complete_plan_and_heartbeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_without_source = _planned()
    planned = replace(
        planned_without_source,
        config_source=ConfigRegistryRunConfigSource(
            selector="active",
            entry_id="baseline",
            config_ref="config-registry/configs/baseline.json",
            content_hash=config_content_hash(planned_without_source.config),
            registry_generation=3,
        ),
    )
    preview = build_run_program_preview(planned.program)

    def fail_preview(_program: RunProgram) -> None:
        pytest.fail("execution admission must not build a preview")

    monkeypatch.setattr(
        runner_module,
        "build_run_program_preview",
        fail_preview,
    )
    heartbeat_seen = Event()
    heartbeat_count = 0
    submissions: list[RunSubmission] = []
    forwarded: dict[str, object] = {}

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        nonlocal heartbeat_count
        path = http_request.url.path
        if path.endswith("/runs"):
            submission = RunSubmission.model_validate_json(http_request.content)
            submissions.append(submission)
            return _model(_admission(submission), status_code=201)
        if path.endswith("/executor/start"):
            return _model(_lease(heartbeat_interval=0.01))
        if path.endswith("/instruments/provision"):
            return _model(_provisioning_receipt(planned.program, http_request))
        if path.endswith("/executor/heartbeat"):
            heartbeat_count += 1
            heartbeat_seen.set()
            return _model(
                _lease(heartbeat_interval=0.01).model_copy(
                    update={"cancellation_requested_at": _NOW}
                )
            )
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    def execute(
        *,
        program: RunProgram,
        session: ExecutionSession,
    ) -> RunManifest:
        forwarded["program"] = program
        accepted = session.accepted
        session.begin()
        assert heartbeat_seen.wait(timeout=1)
        deadline = time.monotonic() + 1
        while not session.cancellation_requested():
            if time.monotonic() >= deadline:
                raise AssertionError("heartbeat did not expose cancellation request")
            time.sleep(0.001)
        return _terminal_manifest(accepted)

    monkeypatch.setattr(runner_module, "execute_admitted_run", execute)

    result = _DaemonRunner(_client(handler), None).execute(
        planned,
        executor_id="notebook-1",
        submission_id="submission-1",
    )
    completed_heartbeats = heartbeat_count
    time.sleep(0.03)

    [submission] = submissions
    assert submission.submission_id == "submission-1"
    assert submission.config == planned.config
    assert submission.config_source == planned.config_source
    assert submission.request == planned.request
    assert submission.plan.experiment_id == preview.experiment_id
    assert submission.plan.experiment_kind == preview.experiment_kind
    assert submission.plan.point_count == preview.point_count
    assert submission.plan.coordinate_ids == preview.coordinate_ids
    assert submission.plan.record_ids == tuple(record.id for record in preview.records)
    assert submission.plan.host_instrument_order == planned.program.resource_order
    assert planned.program.host is not None
    assert submission.plan.run_resource_requirements == tuple(
        RunResourceRequirement(id=requirement.id, kind=requirement.kind)
        for requirement in planned.program.resource_requirements
    )
    assert forwarded["program"] == planned.program
    assert result.status == "completed"
    assert completed_heartbeats >= 1
    assert heartbeat_count == completed_heartbeats


def test_execute_honors_initial_lease_cancellation_before_remote_effects(
    tmp_path: Path,
) -> None:
    planned = _planned()
    requests: list[str] = []
    admissions: list[RunAdmission] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        path = http_request.url.path
        requests.append(path)
        if path.endswith("/runs"):
            submission = RunSubmission.model_validate_json(http_request.content)
            admission = _admission(submission)
            admissions.append(admission)
            return _model(admission, status_code=201)
        if path.endswith("/executor/start"):
            return _model(
                _lease(heartbeat_interval=10).model_copy(
                    update={"cancellation_requested_at": _NOW}
                )
            )
        if path.endswith("/terminal"):
            command = TerminalRunCommitCommand.model_validate_json(http_request.content)
            assert command.outcome.result == "cancelled"
            assert command.outcome.certainty == "known"
            return _model(
                admissions[-1].manifest.model_copy(
                    update={
                        "outcome": command.outcome,
                        "contents": command.contents,
                    }
                )
            )
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    with pytest.raises(RunCancelled) as error:
        _DaemonRunner(_client(handler), None).execute(
            planned,
            executor_id="notebook-1",
        )

    assert error.value.outcome.result == "cancelled"
    assert requests == [
        "/api/v1/runs",
        "/api/v1/runs/run-1/executor/start",
        "/api/v1/runs/run-1/terminal",
    ]


def test_execute_fences_effects_after_heartbeat_loses_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned = _planned()
    heartbeat_attempted = Event()
    admissions: list[RunAdmission] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        path = http_request.url.path
        if path.endswith("/runs"):
            submission = RunSubmission.model_validate_json(http_request.content)
            admission = _admission(submission)
            admissions.append(admission)
            return _model(admission, status_code=201)
        if path.endswith("/executor/start"):
            return _model(_lease(heartbeat_interval=0.005))
        if path.endswith("/instruments/provision"):
            return _model(_provisioning_receipt(planned.program, http_request))
        if path.endswith("/executor/heartbeat"):
            heartbeat_attempted.set()
            return httpx2.Response(409, json={"detail": "executor lease expired"})
        if path.endswith("/terminal"):
            return _model(
                admissions[-1].manifest.model_copy(
                    update={
                        "outcome": RunOutcome(
                            run_id=admissions[-1].manifest.run_id,
                            result="succeeded",
                            certainty="known",
                        )
                    }
                )
            )
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    def execute(
        *,
        program: RunProgram,
        session: ExecutionSession,
    ) -> RunManifest:
        del program
        session.begin()
        assert heartbeat_attempted.wait(timeout=1)
        terminal = TerminalRunCommit(
            run_id=session.run_id,
            outcome=RunOutcome(
                run_id=session.run_id,
                result="succeeded",
                certainty="known",
            ),
        )
        deadline = time.monotonic() + 1
        while True:
            session.commit_terminal(terminal)
            if time.monotonic() >= deadline:
                raise AssertionError("heartbeat failure did not fence effects")
            time.sleep(0.001)

    monkeypatch.setattr(runner_module, "execute_admitted_run", execute)

    with pytest.raises(
        ExecutorLeaseLostError,
        match=r"lease 'lease-1'.*is no longer live",
    ) as error:
        _DaemonRunner(_client(handler), None).execute(
            planned,
            executor_id="notebook-1",
        )

    assert isinstance(error.value.cause, DaemonConflictError)


def test_executor_heartbeat_recovers_from_temporary_unavailability() -> None:
    lease = _lease(heartbeat_interval=0.05)
    supervisor = runner_module._LeaseHeartbeat()
    recovered = Event()
    attempts = 0

    def heartbeat() -> ExecutorLease:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DaemonUnavailableError(
                "project database writer is busy",
                response=httpx2.Response(503),
            )
        recovered.set()
        return lease.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(seconds=0.15)}
        )

    supervisor.start(lease, heartbeat)
    try:
        assert recovered.wait(timeout=1)
        supervisor.require_live()
        assert attempts == 2
    finally:
        supervisor.close()


def test_config_operations_reject_a_draft_from_a_different_active_snapshot() -> None:
    active_config = load_config()
    stale_config = active_config.model_copy(update={"id": "stale-config"})
    entry, activation = _config_registry_records(active_config)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert request.url.path == "/api/v1/config-registry/active"
        return _model(
            ActiveConfigView(
                entry=entry,
                activation=activation,
                config=active_config,
            )
        )

    draft = ConfigDraft(stale_config).replace_scalar(
        "drive_frequency",
        Quantity(value=5.1, unit="GHz"),
    )

    with pytest.raises(ValueError, match="no longer the active"):
        LabClient(_client(handler)).config.preview(draft)

    assert len(requests) == 1


def test_lab_client_owns_local_config_draft_workflow() -> None:
    config = load_config()
    entry, activation = _config_registry_records(config)
    preview = _config_draft_preview(
        config=config,
        entry=entry,
        activation=activation,
        candidate_id="notebook-tuning",
    )
    publishes: list[ConfigPublishCommand] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/v1/config-registry":
            return _model(ConfigRegistryView(entries=(entry,), activation=activation))
        if path == "/api/v1/config-registry/active" and request.method == "GET":
            return _model(
                ActiveConfigView(entry=entry, activation=activation, config=config)
            )
        if path == "/api/v1/config-registry/drafts/preview":
            return _model(preview)
        if path == "/api/v1/config-registry/default":
            command = ConfigPublishCommand.model_validate_json(request.content)
            publishes.append(command)
            return _model(
                _config_draft_default_receipt(command, preview, activation),
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    lab = LabClient(_client(handler), operator="notebook-operator")
    draft = lab.config.edit().replace_scalar(
        "drive_frequency",
        Quantity(value=5.1, unit="GHz"),
    )
    receipt = lab.config.set_default(
        draft,
        entry_id="notebook-tuning",
        note="typed notebook edit",
    )

    assert receipt.entry.id == "notebook-tuning"
    assert publishes[0].actor == "notebook-operator"
    source = publishes[0].source
    assert isinstance(source, ManualConfigDraftRevisionSource)
    assert source.expected_result_content_hash == preview.result_content_hash


def test_lab_config_intents_hide_registry_coordination() -> None:
    config = load_config()
    entry, activation = _config_registry_records(config)
    seen: list[ConfigPublishCommand | ConfigUndoCommand] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/v1/config-registry":
            return _model(ConfigRegistryView(entries=(entry,), activation=activation))
        if path == "/api/v1/config-registry/active" and request.method == "GET":
            return _model(
                ActiveConfigView(entry=entry, activation=activation, config=config)
            )
        if path == "/api/v1/config-registry/default":
            command = ConfigPublishCommand.model_validate_json(request.content)
            seen.append(command)
            return _model(
                ConfigPublishReceipt(
                    entry=entry,
                    activation=activation,
                )
            )
        if path == "/api/v1/config-registry/undo":
            command = ConfigUndoCommand.model_validate_json(request.content)
            seen.append(command)
            return _model(
                ConfigActivationReceipt(
                    activation=activation,
                )
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    lab = LabClient(_client(handler), operator="notebook-operator")

    set_receipt = lab.config.set_default(config, note="use tuned values")
    undo_receipt = lab.config.undo(note="restore prior values")

    assert set_receipt.entry == entry
    assert undo_receipt.activation == activation
    assert seen == [
        ConfigPublishCommand(
            source=DirectConfigRevisionSource(config=config),
            entry_id=config_revision_entry_id(config),
            actor="notebook-operator",
            expected_generation=activation.generation,
            note="use tuned values",
        ),
        ConfigUndoCommand(
            actor="notebook-operator",
            expected_generation=activation.generation,
            note="restore prior values",
        ),
    ]


def test_lab_config_inventory_migration_assembles_registry_coordination() -> None:
    config = load_config()
    entry, activation = _config_registry_records(config)
    changes = (
        InstrumentInventoryRekey(
            instrument_id="source-0",
            from_exclusivity_key="source-0",
            to_exclusivity_key="rack-a/source",
        ),
    )
    migrated_entry = ConfigRegistryEntry(
        id="inventory-v2",
        config_ref="config-registry/entries/inventory-v2/config.json",
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        actor="notebook-operator",
        note="move source",
        recorded_at=_NOW + timedelta(seconds=1),
    )
    receipt = InstrumentInventoryMigrationReceipt(
        entry=migrated_entry,
        activation=ConfigRegistryActivationRecord(
            generation=activation.generation + 1,
            action="inventory_migration",
            entry_id=migrated_entry.id,
            entry_content_hash=migrated_entry.content_hash,
            previous_entry_id=entry.id,
            previous_entry_content_hash=entry.content_hash,
            actor="notebook-operator",
            note="move source",
            recorded_at=_NOW + timedelta(seconds=1),
        ),
        changes=changes,
    )
    seen: list[InstrumentInventoryMigrationCommand] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/v1/config-registry":
            return _model(ConfigRegistryView(entries=(entry,), activation=activation))
        if path == "/api/v1/config-registry/instrument-inventory-migrations":
            seen.append(
                InstrumentInventoryMigrationCommand.model_validate_json(request.content)
            )
            return _model(receipt)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    lab = LabClient(_client(handler), operator="notebook-operator")

    assert (
        lab.config.migrate_instrument_inventory(
            config,
            changes=changes,
            entry_id=migrated_entry.id,
            note="move source",
        )
        == receipt
    )
    assert seen == [
        InstrumentInventoryMigrationCommand(
            config=config,
            entry_id=migrated_entry.id,
            changes=changes,
            actor="notebook-operator",
            expected_generation=activation.generation,
            note="move source",
        )
    ]


def test_run_invocation_plans_against_explicit_snapshot_without_local_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    catalog = _instrument_catalog(config)
    system = ExperimentSystem(instrument_catalog=catalog)
    captured: dict[str, object] = {}

    def execute_run(
        self: _DaemonRunner,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
    ) -> RunManifest:
        del self
        captured.update(
            planned=planned,
            executor_id=executor_id,
            submission_id=submission_id,
        )
        accepted = RunManifest(
            run_id="run-scratch",
            config_content_hash=planned.program.config_content_hash,
        )
        return _terminal_manifest(accepted)

    monkeypatch.setattr(_DaemonRunner, "execute", execute_run)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/instrument-contracts/resolve"
        assert (
            InstrumentContractCatalogRequest.model_validate_json(request.content).config
            == config
        )
        return _model(catalog)

    result = _DaemonRunner(
        _client(handler),
        lambda _config, _catalog: system,
    ).run(
        load_invocation(),
        config=config,
        name="scratch fit",
        tags=("calibration", "demo"),
        description="fit one trace",
        metadata={"sample": "q0"},
        operator="alice",
        executor_id="notebook-1",
        submission_id="scratch-submission",
    )

    planned = captured["planned"]
    assert isinstance(planned, PlannedRun)
    assert planned.config == config
    assert planned.request.operator == "alice"
    assert planned.request.display_name == "scratch fit"
    assert planned.request.tags == ("calibration", "demo")
    assert planned.request.description == "fit one trace"
    assert planned.request.metadata == {"sample": "q0"}
    assert captured["executor_id"] == "notebook-1"
    assert captured["submission_id"] == "scratch-submission"
    planned_system = planned.system
    assert planned_system is not None
    assert planned_system is system
    assert planned_system.instrument_catalog == catalog
    assert result.status == "completed"


def test_run_invocation_uses_active_config_and_bound_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    entry, activation = _config_registry_records(config)
    catalog = _instrument_catalog(config)
    system = ExperimentSystem(instrument_catalog=catalog)
    captured: dict[str, object] = {}
    built_from: list[tuple[ConfigProfileSnapshot, InstrumentContractCatalog]] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        if http_request.url.path == "/api/v1/config-registry/active":
            return _model(
                ActiveConfigView(entry=entry, activation=activation, config=config)
            )
        assert http_request.url.path == "/api/v1/instrument-contracts/resolve"
        assert (
            InstrumentContractCatalogRequest.model_validate_json(
                http_request.content
            ).config
            == config
        )
        return _model(catalog)

    def execute_run(
        self: _DaemonRunner,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
    ) -> RunManifest:
        del self, executor_id, submission_id
        captured["planned"] = planned
        return _terminal_manifest(
            RunManifest(
                run_id="run-scratch",
                config_content_hash=planned.program.config_content_hash,
            )
        )

    monkeypatch.setattr(_DaemonRunner, "execute", execute_run)

    def build_experiment_system(
        selected: ConfigProfileSnapshot,
        instrument_catalog: InstrumentContractCatalog,
    ) -> ExperimentSystem:
        built_from.append((selected, instrument_catalog))
        return system

    result = _DaemonRunner(
        _client(handler),
        build_experiment_system,
    ).run(load_invocation())

    planned = captured["planned"]
    assert isinstance(planned, PlannedRun)
    assert planned.config == config
    planned_system = planned.system
    assert planned_system is not None
    assert planned_system is system
    assert planned_system.instrument_catalog == catalog
    assert built_from == [(config, catalog)]
    assert result.status == "completed"


def test_run_invocation_uses_daemon_catalog_without_a_local_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    catalog = _instrument_catalog(config)
    captured: dict[str, object] = {}

    def execute_run(
        self: _DaemonRunner,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
    ) -> RunManifest:
        del self, executor_id, submission_id
        captured["planned"] = planned
        return _terminal_manifest(
            RunManifest(
                run_id="run-scratch",
                config_content_hash=planned.program.config_content_hash,
            )
        )

    monkeypatch.setattr(_DaemonRunner, "execute", execute_run)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/instrument-contracts/resolve"
        assert (
            InstrumentContractCatalogRequest.model_validate_json(request.content).config
            == config
        )
        return _model(catalog)

    runner = _DaemonRunner(
        _client(handler),
        None,
    )

    result = runner.run(load_invocation(), config=config)

    planned = captured["planned"]
    assert isinstance(planned, PlannedRun)
    assert planned.system == ExperimentSystem(instrument_catalog=catalog)
    assert result.status == "completed"


def test_preview_invocation_uses_active_config_without_admission() -> None:
    config = load_config()
    entry, activation = _config_registry_records(config)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == "/api/v1/config-registry/active":
            return _model(
                ActiveConfigView(entry=entry, activation=activation, config=config)
            )
        assert request.url.path == "/api/v1/instrument-contracts/resolve"
        assert (
            InstrumentContractCatalogRequest.model_validate_json(request.content).config
            == config
        )
        return _model(_instrument_catalog(config))

    preview = _DaemonRunner(
        _client(handler),
        lambda _config, catalog: ExperimentSystem(instrument_catalog=catalog),
    ).preview(load_invocation())

    assert preview.point_count is not None
    assert preview.point_count > 0
    assert [request.url.path for request in requests] == [
        "/api/v1/config-registry/active",
        "/api/v1/instrument-contracts/resolve",
    ]


def _planned() -> PlannedRun:
    config = load_config()
    return plan_configured_experiment(
        load_invocation(),
        config=config,
        system=ExperimentSystem(
            instrument_catalog=_instrument_catalog(config),
        ),
    )


def _instrument_catalog(
    config: ConfigProfileSnapshot,
) -> InstrumentContractCatalog:
    provider = TestSignalInstrumentProvider()
    described = provider.describe(
        InstrumentProviderContext(bindings=instrument_bindings(config))
    )
    return InstrumentContractCatalog(
        config_content_hash=config_content_hash(config),
        provider_id=described.provider_id,
        instruments=described.instruments,
        problems=described.problems,
    )


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> DaemonClient:
    return DaemonClient(
        "http://daemon.local",
        transport=httpx2.MockTransport(handler),
    )


def _config_registry_records(
    config: ConfigProfileSnapshot,
) -> tuple[
    ConfigRegistryEntry,
    ConfigRegistryActivationRecord,
]:
    entry = ConfigRegistryEntry(
        id="baseline",
        config_ref="config-registry/entries/baseline/config.json",
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        actor="notebook",
        recorded_at=_NOW,
    )
    activation = ConfigRegistryActivationRecord(
        generation=1,
        action="activation",
        entry_id=entry.id,
        entry_content_hash=entry.content_hash,
        actor="operator",
        recorded_at=_NOW,
    )
    return entry, activation


def _config_draft_preview(
    *,
    config: ConfigProfileSnapshot,
    entry: ConfigRegistryEntry,
    activation: ConfigRegistryActivationRecord,
    candidate_id: str,
) -> ConfigDraftPreview:
    check = (
        ConfigDraft(config)
        .replace_scalar(
            "drive_frequency",
            Quantity(value=5.1, unit="GHz"),
        )
        .check(candidate_id=candidate_id)
    )
    assert check.candidate is not None
    return ConfigDraftPreview(
        valid=True,
        base_entry=entry,
        base_generation=activation.generation,
        base_content_hash=entry.content_hash,
        config=check.candidate,
        result_content_hash=config_content_hash(check.candidate),
        deltas=check.deltas,
        problems=check.problems,
    )


def _config_draft_default_receipt(
    command: ConfigPublishCommand,
    preview: ConfigDraftPreview,
    previous_activation: ConfigRegistryActivationRecord,
) -> ConfigPublishReceipt:
    assert preview.result_content_hash is not None
    assert command.entry_id is not None
    source = command.source
    assert isinstance(source, ManualConfigDraftRevisionSource)
    entry = ConfigRegistryEntry(
        id=command.entry_id,
        config_ref=f"config-registry/entries/{command.entry_id}/config.json",
        content_hash=preview.result_content_hash,
        source=ManualConfigDraftRegistrySource(
            base_entry_id=source.draft.base_entry_id,
            base_config_content_hash=source.draft.base_content_hash,
            base_registry_generation=source.draft.base_generation,
        ),
        actor=command.actor,
        note=command.note,
    )
    activation = ConfigRegistryActivationRecord(
        generation=previous_activation.generation + 1,
        action="activation",
        entry_id=entry.id,
        entry_content_hash=entry.content_hash,
        previous_entry_id=previous_activation.entry_id,
        previous_entry_content_hash=previous_activation.entry_content_hash,
        actor=command.actor,
        note=command.note,
        recorded_at=_NOW + timedelta(seconds=1),
    )
    return ConfigPublishReceipt(
        entry=entry,
        deltas=preview.deltas,
        activation=activation,
    )


def _admission(submission: RunSubmission) -> RunAdmission:
    return RunAdmission(
        submission_id=submission.submission_id,
        manifest=RunManifest(
            run_id="run-1",
            created_at=_NOW,
            config_content_hash=config_content_hash(submission.config),
            config_source=submission.config_source,
        ),
    )


def _lease(*, heartbeat_interval: float) -> ExecutorLease:
    issued_at = datetime.now(UTC)
    return ExecutorLease(
        lease_id="lease-1",
        run_id="run-1",
        executor_id="notebook-1",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=heartbeat_interval * 3),
        heartbeat_interval_seconds=heartbeat_interval,
    )


def _provisioning_receipt(
    program: RunProgram,
    request: httpx2.Request,
) -> RunInstrumentProvisionReceipt:
    command = RunInstrumentProvisionCommand.model_validate_json(request.content)
    host = program.host
    instrument_ids = () if host is None else host.resource_order
    return RunInstrumentProvisionReceipt(
        run_id="run-1",
        operation_id=command.operation_id,
        status="ready",
        instrument_ids=instrument_ids,
        observed_state=tuple(
            InstrumentStateSnapshot(instrument_id=instrument_id)
            for instrument_id in instrument_ids
        ),
        baseline_state=tuple(
            InstrumentStateSnapshot(instrument_id=instrument_id)
            for instrument_id in instrument_ids
        ),
    )


def _terminal_manifest(accepted: RunManifest) -> RunManifest:
    outcome = RunOutcome(
        run_id=accepted.run_id,
        result="succeeded",
        certainty="known",
    )
    return accepted.model_copy(
        update={
            "outcome": outcome,
        }
    )


def _model(model: BaseModel, *, status_code: int = 200) -> httpx2.Response:
    return httpx2.Response(status_code, json=model.model_dump(mode="json"))
