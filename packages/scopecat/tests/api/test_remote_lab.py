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

import scopecat.api._runner as runner_module
from scopecat.api._config import LabConfigOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.lab import (
    LabClient,
    PreparedLabExperiment,
    RunSequence,
    SequenceProposal,
    SequenceRun,
)
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
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigRegistryView,
    MeasurementPage,
    RunAdmissionView,
    RunConfigView,
    RunControlView,
    RunDetail,
    RunPlanView,
    RunRequestView,
    RunSummary,
    RunSummaryPage,
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
from scopecat.measurements.results import Dataset
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
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunManifest,
    RunSequenceLineage,
    RunSequenceTransition,
)
from scopecat.records.run_request import RunRequest
from scopecat.runs.data import RunArtifactJsonResult
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments import InstrumentProviderContext
from tests.testkit.measurement_models import signal_point_schema, signal_record
from tests.testkit.runtime import plan_experiment, sqlite_project_services
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import (
    load_config,
    load_invocation,
)


def _capture_sequence_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> list[RunSequenceTransition]:
    events: list[RunSequenceTransition] = []

    def attach(
        _run: RunHandle,
        *args: object,
        **kwargs: object,
    ) -> RunContentEntry:
        assert not args
        assert kwargs["kind"] == "run-sequence-transition"
        text = kwargs["text"]
        key = kwargs["key"]
        assert isinstance(text, str)
        assert isinstance(key, str)
        events.append(RunSequenceTransition.model_validate_json(text))
        return RunContentEntry(
            role="artifact",
            id=key,
            kind="run-sequence-transition",
            content_hash="sha256:" + "0" * 64,
        )

    monkeypatch.setattr(RunHandle, "attach", attach)
    return events


_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)
_PROPOSAL_ID = "sha256:" + "0" * 64


def test_remote_run_measurement_batches_use_typed_and_arrow_page_endpoints() -> None:
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
                ),
                admitted_at=_NOW,
            ),
            state="closed",
            updated_at=_NOW,
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
        if request.url.path == "/api/v1/runs/run-batches/measurements":
            offset = int(request.url.params["offset"])
            limit = int(request.url.params["limit"])
            items = records[offset : offset + limit]
            next_offset = offset + len(items)
            return _model(
                MeasurementPage(
                    items=items,
                    next_offset=next_offset if next_offset < len(records) else None,
                    dataset_schema=schema,
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
                headers=(
                    {"X-Scopecat-Next-Offset": str(next_offset)}
                    if next_offset < len(records)
                    else {}
                ),
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    lab = LabClient(_client(handler))
    run = RunHandle(session=lab, id=manifest.run_id)

    batches = list(run.measurement_batches(batch_size=2))

    assert [[record.point_index for record in batch.records] for batch in batches] == [
        [0, 1],
        [2],
    ]
    assert [batch.dims["point"] for batch in batches] == [2, 1]
    assert [request.url.path for request in requests] == [
        "/api/v1/runs/run-batches",
        "/api/v1/runs/run-batches/measurements",
        "/api/v1/runs/run-batches/measurements",
    ]
    assert [dict(request.url.params) for request in requests[1:]] == [
        {"limit": "2", "offset": "0"},
        {"limit": "2", "offset": "2"},
    ]

    requests.clear()
    reader = cast(
        "Iterator[object]",
        run.measurement_record_batches(
            columns={"signal": "signal"},
            batch_size=2,
        ),
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


def test_lab_sequence_records_durable_lineage_and_candidate_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_events = _capture_sequence_transitions(monkeypatch)
    config = load_config()
    candidate_config = config.model_copy(update={"id": f"{config.id}.candidate"})
    source = ConfigRegistryRunConfigSource(
        selector="active",
        entry_id="baseline",
        config_ref="config-registry/entries/baseline/config.json",
        content_hash=config_content_hash(config),
        registry_generation=1,
    )
    invocations = [load_invocation() for _ in range(3)]
    lab = object.__new__(LabClient)
    lab._config = object.__new__(LabConfigOperations)
    prepared = PreparedLabExperiment(
        lab=lab,
        invocation=invocations[0],
        config=config,
        config_source=source,
    )
    prepare_calls: list[tuple[object, object]] = []
    execute_calls: list[tuple[object, dict[str, object]]] = []

    def prepare(
        _lab: LabClient,
        experiment: object,
        *,
        config: object = None,
    ) -> PreparedLabExperiment:
        prepare_calls.append((experiment, config))
        return prepared

    def execute_invocation(
        _lab: LabClient,
        invocation: object,
        **kwargs: object,
    ) -> RunHandle:
        execute_calls.append((invocation, kwargs))
        return RunHandle(session=lab, id=f"run-{len(execute_calls)}")

    def sequence_manifests(
        _lab: LabClient,
        *,
        sequence_id: str | None = None,
    ) -> tuple[RunManifest, ...]:
        del _lab, sequence_id
        return ()

    monkeypatch.setattr(LabClient, "prepare", prepare)
    monkeypatch.setattr(LabClient, "execute_invocation", execute_invocation)
    monkeypatch.setattr(LabClient, "_sequence_manifests", sequence_manifests)

    def resolve_with_source(
        _config_operations: LabConfigOperations,
        selected: object,
    ) -> tuple[ConfigProfileSnapshot, None]:
        assert selected is candidate_config
        return candidate_config, None

    monkeypatch.setattr(
        LabConfigOperations,
        "resolve_with_source",
        resolve_with_source,
    )
    sequence_dataset = object()

    def measurements(
        _run: RunHandle,
        *,
        selector: str = "raw-measurements",
    ) -> object | None:
        return sequence_dataset if selector == "raw-measurements" else None

    monkeypatch.setattr(
        RunHandle,
        "measurements",
        measurements,
    )
    sequence_runs: list[SequenceRun] = []

    def choose_next(sequence_run: SequenceRun):
        assert sequence_run.measurements() is sequence_dataset
        sequence_runs.append(sequence_run)
        if sequence_run.run_index == 2:
            return None
        return SequenceProposal(
            experiment=invocations[sequence_run.run_index + 1],
            config=candidate_config if sequence_run.run_index == 0 else None,
        )

    result = lab.run_sequence(
        invocations[0],
        next_run=choose_next,
        max_runs=5,
        sequence_id="adaptive-sequence",
        config="active",
        metadata={"campaign": "notebook-demo"},
    )

    assert prepare_calls == [(invocations[0], "active")]
    assert [invocation for invocation, _kwargs in execute_calls] == invocations
    assert [kwargs["config"] for _invocation, kwargs in execute_calls] == [
        config,
        candidate_config,
        candidate_config,
    ]
    assert [kwargs["config_source"] for _invocation, kwargs in execute_calls] == [
        source,
        None,
        None,
    ]
    assert [run.id for run in result.runs] == ["run-1", "run-2", "run-3"]
    assert result.status == "stopped"
    assert result.transitions == tuple(persisted_events)
    assert [event.status for event in result.transitions] == [
        "proposed",
        "proposed",
        "stopped",
    ]
    assert [
        transition.next_config_content_hash for transition in result.transitions[:2]
    ] == [config_content_hash(candidate_config)] * 2
    assert result.latest is result.runs[-1]
    assert sequence_runs[0].previous_run is None
    assert sequence_runs[1].previous_run is result.runs[0]
    assert sequence_runs[2].history == result.runs
    assert [kwargs["metadata"] for _invocation, kwargs in execute_calls] == [
        {"campaign": "notebook-demo"},
    ] * 3
    assert [kwargs["sequence"] for _invocation, kwargs in execute_calls] == [
        RunSequenceLineage(
            sequence_id="adaptive-sequence",
            run_index=index,
            max_runs=5,
            previous_run_id=None if index == 0 else f"run-{index}",
            proposal_id=(
                None if index == 0 else result.transitions[index - 1].proposal_id
            ),
        )
        for index in range(3)
    ]
    assert [kwargs["submission_id"] for _invocation, kwargs in execute_calls] == [
        f"sequence:adaptive-sequence:{index}" for index in range(3)
    ]

    limited = lab.run_sequence(
        invocations[0],
        next_run=lambda _run: invocations[0],
        max_runs=4,
        max_new_runs=2,
    )

    assert len(limited.sequence_runs) == 2
    assert limited.status == "awaiting_decision"

    exhausted = lab.run_sequence(
        invocations[0],
        next_run=lambda _run: pytest.fail("budget must stop before policy callback"),
        max_runs=1,
    )

    assert len(exhausted.sequence_runs) == 1
    assert exhausted.status == "budget_exhausted"
    assert exhausted.is_terminal
    assert [transition.status for transition in exhausted.transitions] == [
        "budget_exhausted"
    ]
    exhausted_lineage = execute_calls[-1][1]["sequence"]
    assert isinstance(exhausted_lineage, RunSequenceLineage)
    assert exhausted_lineage.max_runs == 1

    with pytest.raises(ValueError, match="sequence_id must be non-empty"):
        lab.run_sequence(
            invocations[0],
            next_run=lambda _run: None,
            sequence_id="",
        )
    with pytest.raises(ValueError, match="max_runs must be positive"):
        lab.run_sequence(invocations[0], next_run=lambda _run: None, max_runs=0)
    with pytest.raises(ValueError, match="max_new_runs must be positive"):
        lab.run_sequence(
            invocations[0],
            next_run=lambda _run: None,
            max_new_runs=0,
        )


def test_run_sequence_collects_typed_results_without_losing_run_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = object.__new__(LabClient)
    runs = tuple(RunHandle(session=lab, id=f"run-{index}") for index in range(2))
    sequence_runs = tuple(
        SequenceRun(
            sequence_id="result-sequence",
            run_index=index,
            run=run,
            history=runs[: index + 1],
        )
        for index, run in enumerate(runs)
    )

    class FakeDataset:
        def __init__(self, run_id: str) -> None:
            self.run_id = run_id

        @property
        def result(self) -> str:
            return f"stored:{self.run_id}"

        def bind(self, output: object) -> tuple[str, object]:
            return self.run_id, output

    datasets = {
        run.id: cast("Dataset", cast("object", FakeDataset(run.id))) for run in runs
    }
    loads: list[tuple[str, str]] = []

    def measurements(
        run: RunHandle,
        *,
        selector: str = "raw-measurements",
    ) -> Dataset:
        loads.append((run.id, selector))
        return datasets[run.id]

    monkeypatch.setattr(RunHandle, "measurements", measurements)
    sequence = RunSequence(
        sequence_id="result-sequence",
        sequence_runs=sequence_runs,
    )

    results = sequence.results(selector="calibrated")
    output = object()

    assert results.sequence_runs == sequence_runs
    assert results.datasets == tuple(datasets[run.id] for run in runs)
    assert results.stored == ("stored:run-0", "stored:run-1")
    assert results.bind(output) == (("run-0", output), ("run-1", output))
    assert loads == [("run-0", "calibrated"), ("run-1", "calibrated")]


def test_sequence_proposal_recovery_requires_the_same_request_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_transitions = _capture_sequence_transitions(monkeypatch)
    lab = object.__new__(LabClient)
    config = load_config()
    invocation = load_invocation()
    run = RunHandle(session=lab, id="run-proposal-source")
    sequence_run = SequenceRun(
        sequence_id="recovery-sequence",
        run_index=0,
        run=run,
        history=(run,),
    )

    first = lab._evaluate_sequence_run(
        sequence_run,
        lambda _run: invocation,
        run_index=1,
        max_runs=3,
        current_config=config,
        current_config_source=None,
        name="Calibration",
        tags=("recovery",),
        description="durable proposal",
        metadata={"campaign": "proposal-recovery"},
        operator="alice",
        ordinal=0,
    )
    replayed = lab._evaluate_sequence_run(
        sequence_run,
        lambda _run: invocation,
        run_index=1,
        max_runs=3,
        current_config=config,
        current_config_source=None,
        name="Calibration",
        tags=("recovery",),
        description="durable proposal",
        metadata={"campaign": "proposal-recovery"},
        operator="alice",
        ordinal=0,
        expected_transition=first.transition,
    )

    assert replayed.transition is first.transition
    assert first.proposal_id == first.transition.proposal_id
    assert first.transition.next_config_content_hash == config_content_hash(config)
    assert first.transition.next_request_content_hash is not None
    assert persisted_transitions == [first.transition]

    with pytest.raises(ValueError, match="no longer reproduces"):
        lab._evaluate_sequence_run(
            sequence_run,
            lambda _run: None,
            run_index=1,
            max_runs=3,
            current_config=config,
            current_config_source=None,
            name="Calibration",
            tags=("recovery",),
            description="durable proposal",
            metadata={"campaign": "proposal-recovery"},
            operator="alice",
            ordinal=0,
            expected_transition=first.transition,
        )
    assert persisted_transitions == [first.transition]


def test_lab_records_proposal_failure_on_the_evaluated_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_events = _capture_sequence_transitions(monkeypatch)
    invocation = load_invocation()
    lab = object.__new__(LabClient)
    prepared = PreparedLabExperiment(
        lab=lab,
        invocation=invocation,
        config=load_config(),
    )

    def prepare(
        _lab: LabClient,
        _experiment: object,
        *,
        config: object = None,
    ) -> PreparedLabExperiment:
        del config
        return prepared

    def execute_invocation(
        _lab: LabClient,
        _invocation: object,
        **_kwargs: object,
    ) -> RunHandle:
        return RunHandle(session=lab, id="run-proposal-failure")

    def sequence_manifests(
        _lab: LabClient,
        *,
        sequence_id: str | None = None,
    ) -> tuple[RunManifest, ...]:
        del sequence_id
        return ()

    monkeypatch.setattr(LabClient, "prepare", prepare)
    monkeypatch.setattr(LabClient, "execute_invocation", execute_invocation)
    monkeypatch.setattr(LabClient, "_sequence_manifests", sequence_manifests)

    def fail_proposal(_run: SequenceRun):
        raise RuntimeError("next-run callback failed")

    with pytest.raises(RuntimeError, match="next-run callback failed"):
        lab.run_sequence(
            invocation,
            next_run=fail_proposal,
            max_runs=2,
            sequence_id="failed-sequence",
        )

    assert [event.status for event in persisted_events] == ["proposal_failed"]
    assert persisted_events[0].details == {"exception_type": "builtins.RuntimeError"}


def test_lab_rediscovers_run_sequences_across_run_pages() -> None:
    config_hash = config_content_hash(load_config())
    new_first = RunManifest(
        run_id="run-new-0",
        config_content_hash=config_hash,
        sequence=RunSequenceLineage(sequence_id="new-sequence", run_index=0),
    )
    new_latest = RunManifest(
        run_id="run-new-1",
        config_content_hash=config_hash,
        sequence=RunSequenceLineage(
            sequence_id="new-sequence",
            run_index=1,
            previous_run_id=new_first.run_id,
            proposal_id=_PROPOSAL_ID,
        ),
    )
    old_first = RunManifest(
        run_id="run-old-0",
        config_content_hash=config_hash,
        sequence=RunSequenceLineage(sequence_id="old-sequence", run_index=0),
    )
    old_latest = RunManifest(
        run_id="run-old-1",
        config_content_hash=config_hash,
        sequence=RunSequenceLineage(
            sequence_id="old-sequence",
            run_index=1,
            previous_run_id=old_first.run_id,
            proposal_id=_PROPOSAL_ID,
        ),
    )
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert request.url.path == "/api/v1/run-sequences"
        before = request.url.params.get("before")
        if before is None:
            return _model(
                RunSummaryPage(
                    items=(_run_summary(new_latest, sequence=5),),
                    next_cursor=4,
                )
            )
        assert before == "4"
        return _model(
            RunSummaryPage(
                items=(
                    _run_summary(old_latest, sequence=3),
                    _run_summary(new_first, sequence=2),
                    _run_summary(old_first, sequence=1),
                )
            )
        )

    lab = LabClient(_client(handler))

    experiments = lab.run_sequences()

    assert [item.sequence_id for item in experiments] == [
        "new-sequence",
        "old-sequence",
    ]
    assert [[run.id for run in item.runs] for item in experiments] == [
        ["run-new-0", "run-new-1"],
        ["run-old-0", "run-old-1"],
    ]
    assert experiments[0].sequence_runs[1].previous_run is experiments[0].runs[0]
    assert [dict(request.url.params) for request in requests] == [
        {"limit": "500"},
        {"limit": "500", "before": "4"},
    ]


def test_lab_rediscovers_durable_sequence_status() -> None:
    sequence_id = "durable-status"
    run_id = "run-durable-status"
    event = RunSequenceTransition(
        sequence_id=sequence_id,
        run_index=0,
        ordinal=0,
        based_on_run_id=run_id,
        status="budget_exhausted",
        details={"max_runs": 1},
    )
    artifact = RunContentEntry(
        role="artifact",
        id="sequence-transition-0-0",
        kind="run-sequence-transition",
        media_type="application/json",
        content_hash="sha256:" + "1" * 64,
    )
    manifest = RunManifest(
        run_id=run_id,
        config_content_hash=config_content_hash(load_config()),
        sequence=RunSequenceLineage(
            sequence_id=sequence_id,
            run_index=0,
            max_runs=1,
        ),
        contents=(artifact,),
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/v1/run-sequences":
            return _model(RunSummaryPage(items=(_run_summary(manifest, sequence=1),)))
        assert request.url.path == (
            f"/api/v1/runs/{run_id}/artifacts/{artifact.id}/json"
        )
        assert request.url.params["expected_kind"] == "run-sequence-transition"
        return _model(
            RunArtifactJsonResult(
                artifact=artifact,
                content=event.model_dump(mode="json"),
            )
        )

    rediscovered = LabClient(_client(handler)).get_run_sequence(sequence_id)

    assert rediscovered.transitions == (event,)
    assert rediscovered.status == "budget_exhausted"


def test_lab_rejects_starting_an_existing_run_sequence() -> None:
    config_hash = config_content_hash(load_config())
    existing = RunManifest(
        run_id="run-existing-0",
        config_content_hash=config_hash,
        sequence=RunSequenceLineage(sequence_id="existing-sequence", run_index=0),
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/run-sequences"
        assert dict(request.url.params) == {
            "limit": "500",
            "sequence_id": "existing-sequence",
        }
        return _model(RunSummaryPage(items=(_run_summary(existing, sequence=1),)))

    lab = LabClient(_client(handler))

    with pytest.raises(ValueError, match="use resume_sequence"):
        lab.run_sequence(
            load_invocation(),
            next_run=lambda _run: None,
            sequence_id="existing-sequence",
        )


def test_lab_get_run_sequence_rejects_missing_and_broken_sequences() -> None:
    config_hash = config_content_hash(load_config())
    first = RunManifest(
        run_id="run-broken-0",
        config_content_hash=config_hash,
        sequence=RunSequenceLineage(sequence_id="broken", run_index=0),
    )
    broken = RunManifest(
        run_id="run-broken-1",
        config_content_hash=config_hash,
        sequence=RunSequenceLineage(
            sequence_id="broken",
            run_index=1,
            previous_run_id="run-wrong",
            proposal_id=_PROPOSAL_ID,
        ),
    )
    page = RunSummaryPage(
        items=(_run_summary(broken, sequence=2), _run_summary(first, sequence=1))
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/run-sequences"
        assert request.url.params["sequence_id"] == "broken"
        return _model(page)

    lab = LabClient(_client(handler))

    with pytest.raises(ValueError, match="broken predecessor"):
        lab.get_run_sequence("broken")

    empty = LabClient(_client(lambda _request: _model(RunSummaryPage())))
    assert empty.run_sequences() == ()
    with pytest.raises(KeyError, match="not found"):
        empty.get_run_sequence("missing")


def test_lab_resumes_latest_run_with_durable_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_events = _capture_sequence_transitions(monkeypatch)
    config = load_config()
    source = ConfigRegistryRunConfigSource(
        selector="active",
        entry_id="baseline",
        config_ref="config-registry/entries/baseline/config.json",
        content_hash=config_content_hash(config),
        registry_generation=1,
    )
    first = _terminal_manifest(
        RunManifest(
            run_id="run-resume-0",
            config_content_hash=source.content_hash,
            config_source=source,
            sequence=RunSequenceLineage(sequence_id="resume-sequence", run_index=0),
        )
    )
    latest = _terminal_manifest(
        RunManifest(
            run_id="run-resume-1",
            config_content_hash=source.content_hash,
            config_source=source,
            sequence=RunSequenceLineage(
                sequence_id="resume-sequence",
                run_index=1,
                previous_run_id=first.run_id,
                proposal_id=_PROPOSAL_ID,
            ),
        )
    )
    latest_request = RunRequest(
        experiment_id="test.workflow_scan",
        operator="alice",
        metadata={"campaign": "persisted"},
        sequence=latest.sequence,
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/v1/run-sequences":
            assert request.url.params["sequence_id"] == "resume-sequence"
            return _model(
                RunSummaryPage(
                    items=(
                        _run_summary(latest, sequence=2),
                        _run_summary(first, sequence=1),
                    )
                )
            )
        if path == f"/api/v1/runs/{latest.run_id}":
            summary = _run_summary(latest, sequence=2)
            return _model(RunDetail(control=summary.control, manifest=summary.manifest))
        if path == f"/api/v1/runs/{latest.run_id}/config":
            return _model(
                RunConfigView(
                    run_id=latest.run_id,
                    config_content_hash=source.content_hash,
                    config=config,
                )
            )
        if path == f"/api/v1/runs/{latest.run_id}/request":
            return _model(RunRequestView(run_id=latest.run_id, request=latest_request))
        raise AssertionError(f"unexpected request: {request.method} {path}")

    lab = LabClient(_client(handler))
    invocations = [load_invocation(), load_invocation()]
    execute_calls: list[tuple[object, dict[str, object]]] = []

    def execute_invocation(
        _lab: LabClient,
        invocation: object,
        **kwargs: object,
    ) -> RunHandle:
        execute_calls.append((invocation, kwargs))
        return RunHandle(session=lab, id=f"run-resume-{len(execute_calls) + 1}")

    monkeypatch.setattr(LabClient, "execute_invocation", execute_invocation)
    callback_runs: list[SequenceRun] = []

    def choose_next(sequence_run: SequenceRun):
        callback_runs.append(sequence_run)
        return (
            None
            if sequence_run.run_index == 3
            else invocations[sequence_run.run_index - 1]
        )

    resumed = lab.resume_sequence(
        "resume-sequence",
        next_run=choose_next,
        max_new_runs=4,
    )

    assert [sequence_run.run_index for sequence_run in callback_runs] == [1, 2, 3]
    assert [run.id for run in resumed.runs] == [
        "run-resume-0",
        "run-resume-1",
        "run-resume-2",
        "run-resume-3",
    ]
    assert resumed.status == "stopped"
    assert resumed.transitions == tuple(persisted_events)
    assert [kwargs["sequence"] for _invocation, kwargs in execute_calls] == [
        RunSequenceLineage(
            sequence_id="resume-sequence",
            run_index=2,
            previous_run_id="run-resume-1",
            proposal_id=resumed.transitions[0].proposal_id,
        ),
        RunSequenceLineage(
            sequence_id="resume-sequence",
            run_index=3,
            previous_run_id="run-resume-2",
            proposal_id=resumed.transitions[1].proposal_id,
        ),
    ]
    assert all(kwargs["config"] == config for _invocation, kwargs in execute_calls)
    assert all(kwargs["config_source"] == source for _, kwargs in execute_calls)
    assert all(
        kwargs["metadata"] == {"campaign": "persisted"} for _, kwargs in execute_calls
    )
    assert all(kwargs["operator"] == "alice" for _, kwargs in execute_calls)


def test_call_limit_defers_latest_callback_until_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_events = _capture_sequence_transitions(monkeypatch)
    config = load_config()
    source = ConfigRegistryRunConfigSource(
        selector="active",
        entry_id="baseline",
        config_ref="config-registry/entries/baseline/config.json",
        content_hash=config_content_hash(config),
        registry_generation=1,
    )
    first = _terminal_manifest(
        RunManifest(
            run_id="run-limit-0",
            config_content_hash=source.content_hash,
            config_source=source,
            sequence=RunSequenceLineage(
                sequence_id="limit-sequence",
                run_index=0,
                max_runs=4,
            ),
        )
    )
    latest = _terminal_manifest(
        RunManifest(
            run_id="run-limit-1",
            config_content_hash=source.content_hash,
            config_source=source,
            sequence=RunSequenceLineage(
                sequence_id="limit-sequence",
                run_index=1,
                max_runs=4,
                previous_run_id=first.run_id,
                proposal_id=_PROPOSAL_ID,
            ),
        )
    )
    latest_request = RunRequest(
        operator="alice",
        metadata={"campaign": "limited"},
        sequence=latest.sequence,
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/v1/run-sequences":
            assert request.url.params["sequence_id"] == "limit-sequence"
            return _model(RunSummaryPage())
        if path == f"/api/v1/runs/{latest.run_id}":
            summary = _run_summary(latest, sequence=2)
            return _model(RunDetail(control=summary.control, manifest=summary.manifest))
        if path == f"/api/v1/runs/{latest.run_id}/config":
            return _model(
                RunConfigView(
                    run_id=latest.run_id,
                    config_content_hash=source.content_hash,
                    config=config,
                )
            )
        if path == f"/api/v1/runs/{latest.run_id}/request":
            return _model(RunRequestView(run_id=latest.run_id, request=latest_request))
        raise AssertionError(f"unexpected request: {request.method} {path}")

    lab = LabClient(_client(handler))
    invocation = load_invocation()
    prepared = PreparedLabExperiment(
        lab=lab,
        invocation=invocation,
        config=config,
        config_source=source,
    )
    execute_calls: list[dict[str, object]] = []

    def prepare(
        _lab: LabClient,
        _experiment: object,
        *,
        config: object = None,
    ) -> PreparedLabExperiment:
        del config
        return prepared

    monkeypatch.setattr(LabClient, "prepare", prepare)

    def execute_invocation(
        _lab: LabClient,
        _invocation: object,
        **kwargs: object,
    ) -> RunHandle:
        execute_calls.append(kwargs)
        return RunHandle(session=lab, id=f"run-limit-{len(execute_calls) - 1}")

    monkeypatch.setattr(LabClient, "execute_invocation", execute_invocation)
    callback_indices: list[int] = []

    def choose_next(sequence_run: SequenceRun):
        callback_indices.append(sequence_run.run_index)
        return invocation

    limited = lab.run_sequence(
        invocation,
        next_run=choose_next,
        max_runs=4,
        max_new_runs=2,
        sequence_id="limit-sequence",
    )

    assert callback_indices == [0]
    assert [sequence_run.run_index for sequence_run in limited.sequence_runs] == [0, 1]
    assert limited.status == "awaiting_decision"

    def get_run_sequence(
        _lab: LabClient,
        _sequence_id: str,
    ) -> RunSequence:
        return limited

    monkeypatch.setattr(LabClient, "get_run_sequence", get_run_sequence)
    resumed = lab.resume_sequence(
        "limit-sequence",
        next_run=choose_next,
        max_new_runs=1,
    )

    assert callback_indices == [0, 1]
    assert [sequence_run.run_index for sequence_run in resumed.sequence_runs] == [
        0,
        1,
        2,
    ]
    assert resumed.status == "awaiting_decision"
    assert resumed.transitions == tuple(persisted_events)
    assert [event.ordinal for event in resumed.transitions] == [0, 0]
    assert [call["sequence"] for call in execute_calls] == [
        RunSequenceLineage(
            sequence_id="limit-sequence",
            run_index=0,
            max_runs=4,
        ),
        RunSequenceLineage(
            sequence_id="limit-sequence",
            run_index=1,
            max_runs=4,
            previous_run_id="run-limit-0",
            proposal_id=resumed.transitions[0].proposal_id,
        ),
        RunSequenceLineage(
            sequence_id="limit-sequence",
            run_index=2,
            max_runs=4,
            previous_run_id="run-limit-1",
            proposal_id=resumed.transitions[1].proposal_id,
        ),
    ]
    assert [call["submission_id"] for call in execute_calls] == [
        "sequence:limit-sequence:0",
        "sequence:limit-sequence:1",
        "sequence:limit-sequence:2",
    ]


def test_execute_submits_complete_plan_and_heartbeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_without_source = _planned(tmp_path)
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
    planned = _planned(tmp_path)
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
    planned = _planned(tmp_path)
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
    sequence_run = RunSequenceLineage(sequence_id="scratch-sequence", run_index=0)

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
        sequence=sequence_run,
        executor_id="notebook-1",
        submission_id="scratch-submission",
    )

    planned = captured["planned"]
    assert isinstance(planned, PlannedRun)
    assert planned.config == config
    assert planned.request.operator == "alice"
    assert planned.request.sequence == sequence_run
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

    assert preview.point_count > 0
    assert [request.url.path for request in requests] == [
        "/api/v1/config-registry/active",
        "/api/v1/instrument-contracts/resolve",
    ]


def _run_summary(manifest: RunManifest, *, sequence: int) -> RunSummary:
    return RunSummary(
        control=RunControlView(
            sequence=sequence,
            admission=RunAdmissionView(
                run_id=manifest.run_id,
                plan=RunPlanView(
                    experiment_id="sequence-test",
                    experiment_kind="test",
                    point_count=1,
                ),
                admitted_at=manifest.created_at,
            ),
            state="closed",
            updated_at=manifest.created_at,
        ),
        manifest=manifest,
    )


def _planned(tmp_path: Path) -> PlannedRun:
    config = load_config()
    return plan_experiment(
        load_invocation(),
        config=config,
        services=sqlite_project_services(tmp_path),
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
