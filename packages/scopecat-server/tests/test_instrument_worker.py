from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Thread

import psutil
import pytest
from fastapi.testclient import TestClient
from scopecat.adapters.sqlite import SQLiteControlPlane
from scopecat.daemon.views import DaemonHealth
from scopecat.daemon.wire import InstrumentSessionOpenCommand
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.config import ConfigProfileSnapshot, instrument_bindings
from scopecat.records.measurement import ComplexQuantity, MeasurementArray
from scopecat.sdk.instruments import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverPropertyWrite,
    InvokeCommand,
)
from scopecat.sdk.instruments.backend import (
    BackendInvokeRequest,
    BackendOperationArgument,
    BackendPayload,
)
from tests.testkit.instrument_drivers import load_config

from scopecat_server.errors import BackendConflict
from scopecat_server.instrument_backend import (
    InstrumentBackendError,
    InstrumentBackendRejected,
    InstrumentBackendUnavailable,
    InstrumentHandleInvalid,
)
from scopecat_server.instrument_worker import (
    SubprocessInstrumentBackendEndpoint,
)
from scopecat_server.runtime import LocalDaemonRuntime

_FIXTURE = Path(__file__).parent / "fixtures" / "instrument_worker_project"
_BACKEND = "worker_fixture.backend:create_backend"


def test_spawned_worker_executes_closed_driver_requests(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    assert "worker_fixture.backend" not in sys.modules
    endpoint = SubprocessInstrumentBackendEndpoint(project, _BACKEND)
    config = load_config()

    assert "worker_fixture.backend" not in sys.modules
    assert endpoint.healthy
    assert endpoint.worker_pid != os.getpid()
    assert int((project / "worker.pid").read_text(encoding="utf-8")) == (
        endpoint.worker_pid
    )
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    assert endpoint.provider_id == "tests.spawned_provider"
    assert endpoint.payload_catalog.codecs[0].schema_id == "pulse_program"
    describe_context = json.loads(
        (project / "describe-context.json").read_text(encoding="utf-8")
    )
    assert describe_context == {
        "bindings": [binding.model_dump(mode="json")],
    }
    assert set(describe_context["bindings"][0]) == {
        "id",
        "driver_id",
        "connection",
    }

    connection = endpoint.connect(
        binding=binding,
        expected=expected,
    )
    connect_context = json.loads(
        (project / "connect-context.json").read_text(encoding="utf-8")
    )
    assert connect_context == {
        "binding": binding.model_dump(mode="json"),
    }
    assert set(connect_context["binding"]) == {
        "id",
        "driver_id",
        "connection",
    }
    assert not hasattr(connection, "driver")
    endpoint.apply_state(
        connection.handle,
        DriverApplyRequest(
            assignments=(
                DriverPropertyWrite(
                    interface_id="tests.control/v1",
                    property_id="gain",
                    value=StateValue(2.5),
                ),
            )
        ),
    )
    state = endpoint.read_state(connection.handle)
    assert state.metadata["worker_pid"] == endpoint.worker_pid
    assert state.properties[0].value == StateValue(2.5)

    content = b"\x00\xffprogram\x00"
    invoke = endpoint.invoke(
        connection.handle,
        BackendInvokeRequest(
            interface_id="tests.control/v1",
            operation_id="play",
            arguments=(
                BackendOperationArgument(
                    id="program",
                    value=StateValue(PayloadRef(payload_id="program")),
                ),
            ),
            payloads={
                "program": BackendPayload(
                    id="program",
                    schema_id="pulse_program",
                    codec_id="tests.raw",
                    codec_version=1,
                    media_type="application/octet-stream",
                    content=content,
                )
            },
        ),
    )
    assert invoke.metadata == {
        "payload_hex": content.hex(),
        "worker_pid": endpoint.worker_pid,
    }
    assert "worker_fixture.backend" not in sys.modules

    collected = endpoint.collect(
        connection.handle,
        DriverCollectRequest(
            interface_id="tests.control/v1",
            acquisition_id="sample",
            results=(DriverCollectResult(request_id="signal", result_id="signal"),),
        ),
    )
    assert collected.readback is not None
    assert collected.readback.values["signal"] == Quantity(
        value=1.25,
        unit="ratio",
    )

    endpoint.disconnect(connection.handle)
    assert (project / "driver-events.log").read_text(encoding="utf-8") == (
        "disconnect:source-0\n"
    )
    with pytest.raises(InstrumentHandleInvalid, match="stale"):
        endpoint.read_state(connection.handle)

    replacement = endpoint.connect(
        binding=binding,
        expected=expected,
    )
    assert replacement.handle.endpoint_id == connection.handle.endpoint_id
    assert replacement.handle.token != connection.handle.token
    endpoint.abort(replacement.handle)
    endpoint.shutdown()
    endpoint.shutdown()
    assert (project / "driver-events.log").read_text(encoding="utf-8") == (
        "disconnect:source-0\nabort\ndisconnect:source-0\n"
    )
    assert not endpoint.healthy
    assert not psutil.pid_exists(endpoint.worker_pid)


def test_worker_rejects_changed_contract_and_foreign_generation(
    tmp_path: Path,
) -> None:
    first_project = _copy_project(tmp_path / "first")
    second_project = _copy_project(tmp_path / "second")
    first = SubprocessInstrumentBackendEndpoint(first_project, _BACKEND)
    second = SubprocessInstrumentBackendEndpoint(second_project, _BACKEND)
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = first.describe((binding,)).instruments
    connection = first.connect(
        binding=binding,
        expected=expected,
    )

    with pytest.raises(InstrumentHandleInvalid, match="generation"):
        second.read_state(connection.handle)
    with pytest.raises(InstrumentBackendRejected) as rejected:
        first.connect(
            binding=binding,
            expected=expected.model_copy(update={"implementation_version": "changed"}),
        )
    assert [item.code for item in rejected.value.problems] == [
        "instrument_description_changed"
    ]

    first.shutdown()
    second.shutdown()


def test_worker_crash_is_permanent_and_never_restarts(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    endpoint = SubprocessInstrumentBackendEndpoint(project, _BACKEND)
    config = load_config()
    bindings = instrument_bindings(config)
    worker_pid = endpoint.worker_pid
    os.kill(worker_pid, signal.SIGKILL)

    with pytest.raises(InstrumentBackendUnavailable, match="unavailable"):
        endpoint.describe(bindings)
    assert not endpoint.healthy
    with pytest.raises(InstrumentBackendUnavailable, match="unavailable"):
        endpoint.describe(bindings)
    assert endpoint.worker_pid == worker_pid

    endpoint.shutdown()
    assert not psutil.pid_exists(worker_pid)


def test_worker_start_failure_leaves_no_process(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)

    with pytest.raises(
        InstrumentBackendUnavailable,
        match="failed to start",
    ):
        SubprocessInstrumentBackendEndpoint(
            project,
            "worker_fixture.backend:create_failing_backend",
        )

    failed_pid = int((project / "failed-worker.pid").read_text(encoding="utf-8"))
    assert not psutil.pid_exists(failed_pid)


def test_runtime_releases_project_lock_after_worker_start_failure(
    tmp_path: Path,
) -> None:
    project = _copy_project(tmp_path)

    with pytest.raises(InstrumentBackendUnavailable, match="failed to start"):
        LocalDaemonRuntime(
            project,
            instrument_backend_spec="worker_fixture.backend:create_failing_backend",
        )

    with LocalDaemonRuntime(project) as reopened:
        assert reopened.application.health().status == "ok"


def test_worker_crash_degrades_runtime_health(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    with LocalDaemonRuntime(
        project,
        bootstrap_config=load_config(),
        instrument_backend_spec=_BACKEND,
    ) as runtime:
        worker_pid = int((project / "worker.pid").read_text(encoding="utf-8"))
        os.kill(worker_pid, signal.SIGKILL)
        client = TestClient(runtime.app())
        deadline = time.monotonic() + 2
        while (
            health := DaemonHealth.model_validate_json(
                client.get("/api/v1/health").content
            )
        ).status != "degraded":
            if time.monotonic() >= deadline:
                pytest.fail("runtime health did not observe worker failure")
            time.sleep(0.01)

    assert health.status == "degraded"


def test_worker_rejects_lossy_collect_json_without_poisoning_protocol(
    tmp_path: Path,
) -> None:
    project = _copy_project(tmp_path)
    endpoint = SubprocessInstrumentBackendEndpoint(project, _BACKEND)
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    connection = endpoint.connect(
        binding=binding,
        expected=expected,
    )

    valid = endpoint.collect(
        connection.handle,
        DriverCollectRequest(
            interface_id="tests.control/v1",
            acquisition_id="sample",
            results=(
                DriverCollectResult(
                    request_id="signal",
                    result_id="complex_array",
                ),
            ),
        ),
    )
    assert valid.readback is not None
    assert valid.readback.values["signal"] == MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=(1,),
        values=(ComplexQuantity(real=1.0, imag=-0.5, unit="ratio"),),
    )

    with pytest.raises(InstrumentBackendError, match="request failed"):
        endpoint.collect(
            connection.handle,
            DriverCollectRequest(
                interface_id="tests.control/v1",
                acquisition_id="sample",
                results=(
                    DriverCollectResult(
                        request_id="signal",
                        result_id="invalid_array",
                    ),
                ),
            ),
        )
    assert endpoint.healthy
    endpoint.shutdown()


def test_oversized_collect_response_fences_worker_generation(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    endpoint = SubprocessInstrumentBackendEndpoint(project, _BACKEND)
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    connection = endpoint.connect(
        binding=binding,
        expected=expected,
    )

    with pytest.raises(InstrumentBackendUnavailable, match="unavailable"):
        endpoint.collect(
            connection.handle,
            DriverCollectRequest(
                interface_id="tests.control/v1",
                acquisition_id="sample",
                results=(
                    DriverCollectResult(
                        request_id="signal",
                        result_id="oversized_array",
                    ),
                ),
            ),
        )

    assert not endpoint.healthy
    endpoint.shutdown()


def test_shutdown_interrupts_a_blocked_driver_call(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    endpoint = SubprocessInstrumentBackendEndpoint(
        project,
        _BACKEND,
        shutdown_timeout=0.1,
    )
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    connection = endpoint.connect(
        binding=binding,
        expected=expected,
    )
    errors: list[BaseException] = []

    def invoke_blocking_operation() -> None:
        try:
            endpoint.invoke(
                connection.handle,
                BackendInvokeRequest(
                    interface_id="tests.control/v1",
                    operation_id="block",
                ),
            )
        except BaseException as error:
            errors.append(error)

    invocation = Thread(target=invoke_blocking_operation, daemon=True)
    invocation.start()
    _wait_for_marker(project / "driver-blocked-source-0")

    started_at = time.monotonic()
    endpoint.shutdown()
    elapsed = time.monotonic() - started_at
    invocation.join(timeout=2)

    assert elapsed < 0.5
    assert not invocation.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], InstrumentBackendUnavailable)
    assert not psutil.pid_exists(endpoint.worker_pid)


def test_runtime_shutdown_fences_a_blocked_session_and_marks_it_unknown(
    tmp_path: Path,
) -> None:
    project = _copy_project(tmp_path)
    endpoint = SubprocessInstrumentBackendEndpoint(
        project,
        _BACKEND,
        shutdown_timeout=0.1,
    )
    runtime = LocalDaemonRuntime(
        project,
        bootstrap_config=load_config(),
        instrument_endpoint=endpoint,
        instrument_shutdown_grace=timedelta(seconds=0.1),
    )
    instruments = runtime.application.instruments
    session = instruments.open_session(
        InstrumentSessionOpenCommand(
            operation_id="open-blocked-session",
            actor="alice",
            instrument_ids=("source-0",),
        )
    )
    invoke_errors: list[BaseException] = []
    close_errors: list[BaseException] = []

    def invoke_blocking_operation() -> None:
        try:
            instruments.invoke(
                session.session_id,
                "source-0",
                InvokeCommand(
                    command_id="blocked-invoke",
                    instrument_id="source-0",
                    resource_id="source-0",
                    interface_id="tests.control/v1",
                    operation_id="block",
                ),
            )
        except BaseException as error:
            invoke_errors.append(error)

    def close_runtime() -> None:
        try:
            runtime.close()
        except BaseException as error:
            close_errors.append(error)

    invocation = Thread(target=invoke_blocking_operation, daemon=True)
    closing = Thread(target=close_runtime, daemon=True)
    try:
        invocation.start()
        _wait_for_marker(project / "driver-blocked-source-0")
        closing.start()
        closing.join(timeout=2)
        invocation.join(timeout=2)
    finally:
        (project / "driver-release-source-0").touch()
        endpoint.shutdown()
        runtime.close()
        closing.join(timeout=2)
        invocation.join(timeout=2)

    assert not closing.is_alive()
    assert not invocation.is_alive()
    assert not close_errors
    assert len(invoke_errors) == 1
    assert isinstance(invoke_errors[0], BackendConflict)
    assert str(invoke_errors[0]) == "instrument invoke failed with unknown state"
    assert not psutil.pid_exists(endpoint.worker_pid)

    control = SQLiteControlPlane(project / ".scopecat" / "control.sqlite3")
    durable = control.get_instrument_session(session.session_id)
    assert durable.state == "attention_required"
    assert durable.attention_reason == "instrument_invoke_unknown"
    assert durable.active_operation_id == "blocked-invoke"
    assert durable.active_operation_kind == "invoke"
    assert durable.end_status is None
    with control.transaction() as connection:
        [claim] = control.list_resource_claims_in_transaction(connection)
    assert claim.owner_id == session.session_id
    assert claim.status == "quarantined"


def test_blocked_driver_does_not_block_another_device(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    endpoint = SubprocessInstrumentBackendEndpoint(project, _BACKEND)
    config = _two_instrument_config()
    bindings = instrument_bindings(config)
    expected = {
        item.instrument_id: item for item in endpoint.describe(bindings).instruments
    }
    bindings_by_id = {binding.id: binding for binding in bindings}
    first = endpoint.connect(
        binding=bindings_by_id["source-0"],
        expected=expected["source-0"],
    )
    second = endpoint.connect(
        binding=bindings_by_id["source-1"],
        expected=expected["source-1"],
    )
    release = project / "driver-release-source-0"

    try:
        with ThreadPoolExecutor(max_workers=2) as calls:
            blocked = calls.submit(
                endpoint.invoke,
                first.handle,
                BackendInvokeRequest(
                    interface_id="tests.control/v1",
                    operation_id="block",
                ),
            )
            _wait_for_marker(project / "driver-blocked-source-0")
            independent = calls.submit(endpoint.read_state, second.handle)
            try:
                state = independent.result(timeout=1)
            finally:
                release.touch()
            blocked.result(timeout=2)
        assert state.instrument_id == "source-1"
        assert state.metadata["worker_pid"] == endpoint.worker_pid
    finally:
        release.touch()
        endpoint.shutdown()


def _copy_project(root: Path) -> Path:
    project = root / "project"
    project.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_FIXTURE, project)
    return project


def _two_instrument_config() -> ConfigProfileSnapshot:
    config = load_config()
    [source] = config.instrument_registry.instruments
    registry = config.instrument_registry.model_copy(
        update={
            "instruments": [
                source,
                source.model_copy(
                    update={
                        "id": "source-1",
                        "exclusivity_key": "source-1",
                    }
                ),
            ]
        }
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        }
    )


def _wait_for_marker(path: Path) -> None:
    deadline = time.monotonic() + 2
    while not path.exists():
        if time.monotonic() >= deadline:
            pytest.fail(f"fixture driver did not create {path.name}")
        time.sleep(0.01)
