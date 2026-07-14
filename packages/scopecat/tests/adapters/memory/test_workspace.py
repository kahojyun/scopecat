from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_prepared_invocation

from scopecat.adapters.memory import MemoryWorkspaceStore
from scopecat.composition.memory import memory_workspace_services
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.planning.backend import ExecutionBackend
from scopecat.runs.execution import inspect_run_execution
from scopecat.runs.service import start_run


def test_recomposed_services_share_execution_recovery_state(tmp_path: Path) -> None:
    store = MemoryWorkspaceStore()
    initial = memory_workspace_services(store)
    manifest = start_run(
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=initial,
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
    )

    recomposed = memory_workspace_services(store)
    initial_execution = initial.execution
    recomposed_execution = recomposed.execution

    assert recomposed_execution.resources is initial_execution.resources
    assert recomposed_execution.journal_for(
        manifest.run_id
    ) is initial_execution.journal_for(manifest.run_id)
    assert recomposed_execution.measurements_for(
        manifest.run_id
    ) is initial_execution.measurements_for(manifest.run_id)
    assert recomposed_execution.collections_for(
        manifest.run_id
    ) is initial_execution.collections_for(manifest.run_id)
    assert recomposed_execution.payloads_for(
        manifest.run_id
    ) is initial_execution.payloads_for(manifest.run_id)

    initial_inspection = inspect_run_execution(
        run_id=manifest.run_id,
        services=initial,
    )
    recomposed_inspection = inspect_run_execution(
        run_id=manifest.run_id,
        services=recomposed,
    )

    assert initial_inspection.transitions
    assert recomposed_inspection == initial_inspection
    assert recomposed_execution.measurements_for(manifest.run_id).measurements()
    assert recomposed_execution.collections_for(manifest.run_id).receipts()


def test_recomposed_services_share_resource_exclusion() -> None:
    store = MemoryWorkspaceStore()
    first = memory_workspace_services(store).execution.resources
    second = memory_workspace_services(store).execution.resources
    claim = ResourceClaim(id="shared")
    first_entered = Event()
    release_first = Event()
    second_started = Event()
    second_entered = Event()

    def hold_first() -> None:
        with first.acquire((claim,)):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def enter_second() -> None:
        second_started.set()
        with second.acquire((claim,)):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(hold_first)
        assert first_entered.wait(timeout=2)
        second_future = executor.submit(enter_second)
        assert second_started.wait(timeout=2)
        try:
            assert not second_entered.wait(timeout=0.05)
        finally:
            release_first.set()
        first_future.result(timeout=2)
        second_future.result(timeout=2)

    assert second_entered.is_set()
