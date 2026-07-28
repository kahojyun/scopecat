from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Literal, override

import httpx2
import pytest
from fastapi.testclient import TestClient
from scopecat.adapters.sqlite.object_store import ImmutableObjectStore
from scopecat.application import LabApplication
from scopecat.control.models import ResourceKey, RunPlanSummary
from scopecat.daemon.client import DaemonClient, DaemonConflictError
from scopecat.daemon.wire import (
    ExecutorStartRequest,
    InstrumentSessionOpenCommand,
    PayloadObjectReceipt,
    RunHardwareBatchCommand,
    RunInstrumentProvisionCommand,
    RunSubmission,
)
from scopecat.execution.ports.instruments import (
    RunHardwareBatch,
    RunHardwareCollect,
    RunHardwareCollectBinding,
    RunHardwareInvoke,
)
from scopecat.kernel.content_identity import sha256_content_hash
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.planning.provider_validation import instrument_contract_fingerprint
from scopecat.planning.system import ExperimentSystem
from scopecat.records.artifact import CommandPayload, command_payload_from_bytes
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import (
    CollectResultRequest,
    InstrumentOperationArgument,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InvokeCommand,
    InvokeReceipt,
)
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry
from tests.testkit.instrument_drivers import SignalInstrumentDriver, load_config

from scopecat_server import LocalDaemonRuntime
from scopecat_server.payload_service import (
    DEFAULT_MAX_PAYLOAD_OBJECT_BYTES,
    CommandPayloadService,
    CommandPayloadTooLarge,
)

_PAYLOAD_BYTES = b"\x00\xff\x80SCPI\x00program\n"
_MEDIA_TYPE = "application/octet-stream"
_CODEC_ID = "tests.raw-bytes"
_CODEC_VERSION = 1


class _PayloadConsumerDriver(SignalInstrumentDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.consumed_payloads: list[bytes] = []

    @override
    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        for argument in command.arguments:
            value = argument.value.root
            if isinstance(value, PayloadRef):
                self.consumed_payloads.append(
                    command.payloads[value.payload_id].inline_bytes()
                )
        return super().invoke(command)


class _PayloadProvider:
    provider_id = "tests.payload_transport_provider"

    def __init__(self) -> None:
        self.drivers: list[_PayloadConsumerDriver] = []

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                _PayloadConsumerDriver(instrument_id).describe()
                for instrument_id in _selected_ids(context)
            ),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        drivers = tuple(
            _PayloadConsumerDriver(instrument_id)
            for instrument_id in context.instrument_ids
        )
        self.drivers.extend(drivers)
        return InstrumentProviderResult(drivers=drivers)


def test_binary_command_payload_crosses_real_json_http_boundary(
    tmp_path: Path,
) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        run_id, lease_id = _start_run(daemon)
        _provision(daemon, run_id, lease_id)
        payload = _inline_payload("program-inline", _PAYLOAD_BYTES)

        receipt = daemon.execute_run_hardware(
            run_id,
            _payload_batch(lease_id, "inline-batch", payload),
        )

        assert receipt.problems == ()
        [driver] = provider.drivers
        assert driver.consumed_payloads == [_PAYLOAD_BYTES]
        [started] = [
            event
            for event in daemon.replay_events(run_id=run_id).items
            if event.kind == "run_hardware_batch_started"
        ]
        evidence = started.model_dump_json()
        assert "content_base64" not in evidence
        assert '"body":' not in evidence


def test_direct_invoke_uses_the_same_payload_object_boundary(
    tmp_path: Path,
) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        session = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-payload-session",
                actor="payload-test",
                instrument_ids=("source-0",),
            )
        )
        payload = _inline_payload("direct-program", _PAYLOAD_BYTES)
        command = InvokeCommand(
            command_id="direct-payload-invoke",
            instrument_id="source-0",
            resource_id="source-0",
            interface_id="test.play_program/v1",
            operation_id="play",
            arguments=[
                InstrumentOperationArgument(
                    id="program",
                    value=StateValue(PayloadRef(payload_id=payload.id)),
                )
            ],
            payloads={payload.id: payload},
        )

        receipt = daemon.invoke_instrument(
            session.session_id,
            "source-0",
            command,
        )
        daemon.close_instrument_session(session.session_id)

        assert receipt.status == "invoked"
        [driver] = provider.drivers
        assert driver.consumed_payloads == [_PAYLOAD_BYTES]
        assert driver.invoked[0].payloads[payload.id].inline_bytes() == _PAYLOAD_BYTES


@pytest.mark.parametrize("first_body_kind", ["inline", "blob"])
def test_direct_invoke_idempotency_uses_payload_content_not_transport_body(
    tmp_path: Path,
    first_body_kind: Literal["inline", "blob"],
) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        session = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id=f"open-canonical-{first_body_kind}",
                actor="payload-test",
                instrument_ids=("source-0",),
            )
        )
        inline = _inline_payload("canonical-program", _PAYLOAD_BYTES)
        stored = _put_session_payload_object(
            transport,
            session.session_id,
            _PAYLOAD_BYTES,
            content_hash=inline.content_hash,
        )
        blob = command_payload_from_bytes(
            id=inline.id,
            schema_id=inline.schema_id,
            codec_id=inline.codec_id,
            codec_version=inline.codec_version,
            media_type=inline.media_type,
            content=_PAYLOAD_BYTES,
            blob_ref=stored.ref,
        )
        commands = {
            "inline": _direct_payload_command(
                "canonical-invoke",
                inline,
            ),
            "blob": _direct_payload_command(
                "canonical-invoke",
                blob,
            ),
        }
        first = commands[first_body_kind]
        second = commands["blob" if first_body_kind == "inline" else "inline"]
        path = (
            f"/api/v1/instrument-sessions/{session.session_id}/"
            "instruments/source-0/invoke"
        )

        first_response = transport.post(
            path,
            json=first.model_dump(mode="json"),
        )
        second_response = transport.post(
            path,
            json=second.model_dump(mode="json"),
        )
        daemon.close_instrument_session(session.session_id)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert second_response.json() == first_response.json()
        [driver] = provider.drivers
        assert len(driver.invoked) == 1
        assert driver.consumed_payloads == [_PAYLOAD_BYTES]


def test_binary_blob_payload_is_materialized_before_driver_call(
    tmp_path: Path,
) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        run_id, lease_id = _start_run(daemon)
        _provision(daemon, run_id, lease_id)
        inline = _inline_payload("program-blob", _PAYLOAD_BYTES)
        stored = _put_run_payload_object(
            transport,
            run_id,
            lease_id,
            _PAYLOAD_BYTES,
            content_hash=inline.content_hash,
        )
        blob = command_payload_from_bytes(
            id=inline.id,
            schema_id=inline.schema_id,
            codec_id=inline.codec_id,
            codec_version=inline.codec_version,
            media_type=inline.media_type,
            content=_PAYLOAD_BYTES,
            blob_ref=stored.ref,
        )

        receipt = daemon.execute_run_hardware(
            run_id,
            _payload_batch(lease_id, "blob-batch", blob),
        )

        assert receipt.problems == ()
        [driver] = provider.drivers
        assert driver.consumed_payloads == [_PAYLOAD_BYTES]


def test_payload_object_upload_rejects_hash_mismatch(tmp_path: Path) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        session = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-hash-mismatch-payload-session",
                actor="payload-test",
                instrument_ids=("source-0",),
            )
        )
        wrong_hexdigest = "0" * 64

        response = transport.put(
            (
                f"/api/v1/instrument-sessions/{session.session_id}/"
                f"payload-objects/{wrong_hexdigest}"
            ),
            content=_PAYLOAD_BYTES,
            headers={"content-type": _MEDIA_TYPE},
        )
        daemon.close_instrument_session(session.session_id)

        assert response.status_code == 422
        assert "hash mismatch" in response.text
        assert not _payload_object_path(
            runtime,
            f"sha256:{wrong_hexdigest}",
        ).exists()
        assert not _payload_object_path(
            runtime,
            sha256_content_hash(_PAYLOAD_BYTES),
        ).exists()
        [driver] = provider.drivers
        assert driver.invoked == []


def test_payload_object_upload_rejects_oversize_before_storage(
    tmp_path: Path,
) -> None:
    provider = _PayloadProvider()
    content = b"must-not-be-stored"
    content_hash = sha256_content_hash(content)
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        session = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-oversize-payload-session",
                actor="payload-test",
                instrument_ids=("source-0",),
            )
        )
        response = transport.put(
            (
                f"/api/v1/instrument-sessions/{session.session_id}/payload-objects/"
                f"{content_hash.removeprefix('sha256:')}"
            ),
            content=content,
            headers={
                "content-length": str(DEFAULT_MAX_PAYLOAD_OBJECT_BYTES + 1),
                "content-type": _MEDIA_TYPE,
            },
        )
        daemon.close_instrument_session(session.session_id)

        assert response.status_code == 413
        assert not _payload_object_path(runtime, content_hash).exists()
        [driver] = provider.drivers
        assert driver.invoked == []


def test_payload_object_stream_enforces_limit_across_chunks(
    tmp_path: Path,
) -> None:
    content = b"five!"
    objects = ImmutableObjectStore(tmp_path / "objects")
    objects.bootstrap()
    service = CommandPayloadService(
        objects,
        max_object_bytes=4,
        max_inline_bytes=4,
    )

    async def chunks() -> AsyncIterator[bytes]:
        yield content[:3]
        yield content[3:]

    with pytest.raises(CommandPayloadTooLarge):
        asyncio.run(
            service.put_object_stream(
                chunks(),
                expected_content_hash=sha256_content_hash(content),
            )
        )

    assert not objects.path_for(sha256_content_hash(content)).exists()


def test_blob_descriptor_is_bounded_before_object_store_read(tmp_path: Path) -> None:
    content = b"five!"
    objects = ImmutableObjectStore(tmp_path / "objects")
    objects.bootstrap()
    service = CommandPayloadService(
        objects,
        max_object_bytes=4,
        max_inline_bytes=4,
    )
    inline = _inline_payload("oversized-blob", content)
    blob = command_payload_from_bytes(
        id=inline.id,
        schema_id=inline.schema_id,
        codec_id=inline.codec_id,
        codec_version=inline.codec_version,
        media_type=inline.media_type,
        content=content,
        blob_ref=inline.content_hash,
    )

    with pytest.raises(CommandPayloadTooLarge):
        service.materialize_invoke_command(
            _direct_payload_command("oversized-blob-invoke", blob)
        )


def test_closed_direct_session_cannot_leave_an_uploaded_payload(
    tmp_path: Path,
) -> None:
    provider = _PayloadProvider()
    content = b"closed-session-must-not-store"
    payload = _inline_payload("closed-session-program", content)
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        session = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-then-close-payload-session",
                actor="payload-test",
                instrument_ids=("source-0",),
            )
        )
        daemon.close_instrument_session(session.session_id)
        object_path = _payload_object_path(runtime, payload.content_hash)
        assert not object_path.exists()

        with pytest.raises(DaemonConflictError):
            daemon.invoke_instrument(
                session.session_id,
                "source-0",
                _direct_payload_command("closed-session-invoke", payload),
            )

        assert not object_path.exists()
        [driver] = provider.drivers
        assert driver.invoked == []
        assert driver.consumed_payloads == []


def test_stale_run_lease_cannot_leave_an_uploaded_payload(tmp_path: Path) -> None:
    provider = _PayloadProvider()
    content = b"stale-lease-must-not-store"
    payload = _inline_payload("stale-lease-program", content)
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        run_id, lease_id = _start_run(daemon)
        _provision(daemon, run_id, lease_id)
        object_path = _payload_object_path(runtime, payload.content_hash)
        assert not object_path.exists()

        with pytest.raises(DaemonConflictError):
            daemon.execute_run_hardware(
                run_id,
                _payload_batch(
                    f"{lease_id}-stale",
                    "stale-lease-batch",
                    payload,
                ),
            )

        assert not object_path.exists()
        [driver] = provider.drivers
        assert driver.invoked == []
        assert driver.consumed_payloads == []


def test_missing_payload_blob_is_rejected_before_driver_call(tmp_path: Path) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        run_id, lease_id = _start_run(daemon)
        _provision(daemon, run_id, lease_id)
        inline = _inline_payload("program-missing", _PAYLOAD_BYTES)
        missing = command_payload_from_bytes(
            id=inline.id,
            schema_id=inline.schema_id,
            codec_id=inline.codec_id,
            codec_version=inline.codec_version,
            media_type=inline.media_type,
            content=_PAYLOAD_BYTES,
            blob_ref=inline.content_hash,
        )

        with pytest.raises(httpx2.HTTPStatusError) as caught:
            daemon.execute_run_hardware(
                run_id,
                _payload_batch(
                    lease_id,
                    "missing-blob-batch",
                    missing,
                ),
            )

        assert caught.value.response.status_code == 422
        assert "payload object was not found" in caught.value.response.text
        [driver] = provider.drivers
        assert driver.consumed_payloads == []
        assert driver.invoked == []


def test_batch_materializes_all_payloads_before_first_driver_call(
    tmp_path: Path,
) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        run_id, lease_id = _start_run(daemon)
        _provision(daemon, run_id, lease_id)
        valid = _inline_payload("program-valid", _PAYLOAD_BYTES)
        missing_content = b"missing-second"
        missing_inline = _inline_payload(
            "program-missing-second",
            missing_content,
        )
        missing = command_payload_from_bytes(
            id=missing_inline.id,
            schema_id=missing_inline.schema_id,
            codec_id=missing_inline.codec_id,
            codec_version=missing_inline.codec_version,
            media_type=missing_inline.media_type,
            content=missing_content,
            blob_ref=missing_inline.content_hash,
        )
        [valid_action] = _payload_batch(
            lease_id,
            "atomic-valid",
            valid,
        ).batch.actions
        [missing_action] = _payload_batch(
            lease_id,
            "atomic-missing",
            missing,
        ).batch.actions
        command = RunHardwareBatchCommand(
            lease_id=lease_id,
            batch=RunHardwareBatch(
                operation_id="atomic-materialization",
                actions=(valid_action, missing_action),
            ),
        )

        with pytest.raises(httpx2.HTTPStatusError) as caught:
            daemon.execute_run_hardware(run_id, command)

        assert caught.value.response.status_code == 422
        [driver] = provider.drivers
        assert driver.consumed_payloads == []
        assert driver.invoked == []
        assert not any(
            event.kind == "run_hardware_batch_started"
            for event in daemon.replay_events(run_id=run_id).items
        )


def test_payload_invocations_are_not_suppressed_by_reused_payload_id(
    tmp_path: Path,
) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        run_id, lease_id = _start_run(daemon)
        _provision(daemon, run_id, lease_id)
        first = _inline_payload("reused-program", b"first-program")
        second = _inline_payload("reused-program", b"second-program")
        [first_action] = _payload_batch(
            lease_id,
            "reused-program-first",
            first,
        ).batch.actions
        [second_action] = _payload_batch(
            lease_id,
            "reused-program-second",
            second,
        ).batch.actions
        command = RunHardwareBatchCommand(
            lease_id=lease_id,
            batch=RunHardwareBatch(
                operation_id="reused-program-content-change",
                actions=(first_action, second_action),
            ),
        )

        receipt = daemon.execute_run_hardware(run_id, command)

        assert receipt.problems == ()
        [driver] = provider.drivers
        assert driver.consumed_payloads == [b"first-program", b"second-program"]
        assert len(driver.invoked) == 2


@pytest.mark.parametrize(
    "invalid_contract",
    ["payload_schema", "payload_codec", "collect"],
)
def test_batch_prevalidates_every_action_before_first_driver_call(
    tmp_path: Path,
    invalid_contract: Literal["payload_schema", "payload_codec", "collect"],
) -> None:
    provider = _PayloadProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        run_id, lease_id = _start_run(daemon)
        _provision(daemon, run_id, lease_id)
        valid = _inline_payload("preflight-valid", b"valid-first-action")
        [valid_action] = _payload_batch(
            lease_id,
            "preflight-valid",
            valid,
        ).batch.actions
        invalid_action = _invalid_contract_action(
            invalid_contract,
            lease_id=lease_id,
        )
        command = RunHardwareBatchCommand(
            lease_id=lease_id,
            batch=RunHardwareBatch(
                operation_id=f"preflight-{invalid_contract}",
                actions=(valid_action, invalid_action),
            ),
        )

        receipt = daemon.execute_run_hardware(run_id, command)

        assert receipt.problems
        [driver] = provider.drivers
        assert driver.consumed_payloads == []
        assert driver.invoked == []
        assert driver.collect_commands == []
        assert not any(
            event.kind == "run_hardware_batch_started"
            for event in daemon.replay_events(run_id=run_id).items
        )


def _runtime(
    root: Path,
    provider: _PayloadProvider,
) -> LocalDaemonRuntime:
    def factory(_root: Path) -> LabApplication:
        return LabApplication(
            build_system=lambda _config: ExperimentSystem(
                provider=provider,
                payload_codecs=_payload_codecs(),
            )
        )

    return LocalDaemonRuntime(
        root,
        bootstrap_config=load_config(),
        application_factory=factory,
    )


def _daemon_client(transport: TestClient) -> DaemonClient:
    def send(request: httpx2.Request) -> httpx2.Response:
        response = transport.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx2.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )


def _put_session_payload_object(
    transport: TestClient,
    session_id: str,
    content: bytes,
    *,
    content_hash: str,
) -> PayloadObjectReceipt:
    response = transport.put(
        (
            f"/api/v1/instrument-sessions/{session_id}/payload-objects/"
            f"{content_hash.removeprefix('sha256:')}"
        ),
        content=content,
        headers={"content-type": _MEDIA_TYPE},
    )
    assert response.status_code == 201
    return PayloadObjectReceipt.model_validate(response.json())


def _put_run_payload_object(
    transport: TestClient,
    run_id: str,
    lease_id: str,
    content: bytes,
    *,
    content_hash: str,
) -> PayloadObjectReceipt:
    response = transport.put(
        (
            f"/api/v1/runs/{run_id}/payload-objects/"
            f"{content_hash.removeprefix('sha256:')}"
        ),
        content=content,
        headers={
            "content-type": _MEDIA_TYPE,
            "x-scopecat-lease-id": lease_id,
        },
    )
    assert response.status_code == 201
    return PayloadObjectReceipt.model_validate(response.json())


def _start_run(daemon: DaemonClient) -> tuple[str, str]:
    config = load_config()
    instrument_ids = ("source-0",)
    fingerprint = instrument_contract_fingerprint(
        _PayloadProvider.provider_id,
        tuple(
            _PayloadConsumerDriver(instrument_id).describe()
            for instrument_id in instrument_ids
        ),
    )
    admission = daemon.submit_run(
        RunSubmission(
            submission_id="payload-transport",
            config=config,
            request=RunRequest(experiment_id="payload-transport"),
            plan=RunPlanSummary(
                experiment_id="payload-transport",
                experiment_kind="payload-transport",
                point_count=1,
                host_instrument_order=instrument_ids,
                host_provider_id=_PayloadProvider.provider_id,
                host_contract_fingerprint=fingerprint,
                run_resource_claims=(ResourceKey(kind="instrument", id="source-0"),),
            ),
        )
    )
    lease = daemon.start_executor(
        admission.run_id,
        ExecutorStartRequest(executor_id="payload-transport-executor"),
    )
    return admission.run_id, lease.lease_id


def _provision(daemon: DaemonClient, run_id: str, lease_id: str) -> None:
    receipt = daemon.provision_run_instruments(
        run_id,
        RunInstrumentProvisionCommand(
            lease_id=lease_id,
            operation_id="payload-transport-provision",
        ),
    )
    assert receipt.status == "ready"


def _inline_payload(payload_id: str, content: bytes) -> CommandPayload:
    return _payload_with_contract(payload_id, content)


def _payload_with_contract(
    payload_id: str,
    content: bytes,
    *,
    schema_id: str = "pulse_program",
    codec_id: str = _CODEC_ID,
) -> CommandPayload:
    return command_payload_from_bytes(
        id=payload_id,
        schema_id=schema_id,
        codec_id=codec_id,
        codec_version=_CODEC_VERSION,
        media_type=_MEDIA_TYPE,
        content=content,
    )


def _direct_payload_command(
    command_id: str,
    payload: CommandPayload,
) -> InvokeCommand:
    return InvokeCommand(
        command_id=command_id,
        instrument_id="source-0",
        resource_id="source-0",
        interface_id="test.play_program/v1",
        operation_id="play",
        arguments=[
            InstrumentOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            )
        ],
        payloads={payload.id: payload},
    )


def _payload_batch(
    lease_id: str,
    operation_id: str,
    payload: CommandPayload,
) -> RunHardwareBatchCommand:
    return RunHardwareBatchCommand(
        lease_id=lease_id,
        batch=RunHardwareBatch(
            operation_id=operation_id,
            actions=(
                RunHardwareInvoke(
                    effect_id=f"{operation_id}.invoke",
                    point_index=0,
                    instrument_id="source-0",
                    resource_id="source-0",
                    interface_id="test.play_program/v1",
                    operation_id="play",
                    arguments=(
                        InstrumentOperationArgument(
                            id="program",
                            value=StateValue(PayloadRef(payload_id=payload.id)),
                        ),
                    ),
                    payloads={payload.id: payload},
                ),
            ),
        ),
    )


def _invalid_contract_action(
    invalid_contract: Literal["payload_schema", "payload_codec", "collect"],
    *,
    lease_id: str,
) -> RunHardwareInvoke | RunHardwareCollect:
    if invalid_contract == "collect":
        return RunHardwareCollect(
            effect_id="preflight-invalid-collect.collect",
            point_index=0,
            instrument_id="source-0",
            point_count=1,
            requests=(
                CollectResultRequest(
                    id="signal",
                    interface_id="test.missing_interface/v1",
                    acquisition_id="sample",
                    result_id="signal",
                ),
            ),
            bindings=(
                RunHardwareCollectBinding(
                    request_id="signal",
                    product_use_ids=("preflight-invalid-collect.signal",),
                ),
            ),
        )
    payload = _payload_with_contract(
        f"preflight-invalid-{invalid_contract}",
        f"invalid-{invalid_contract}".encode(),
        schema_id=(
            "tests.wrong-payload-schema"
            if invalid_contract == "payload_schema"
            else "pulse_program"
        ),
        codec_id=(
            "tests.wrong-codec" if invalid_contract == "payload_codec" else _CODEC_ID
        ),
    )
    [action] = _payload_batch(
        lease_id,
        f"preflight-invalid-{invalid_contract}",
        payload,
    ).batch.actions
    assert isinstance(action, RunHardwareInvoke)
    return action


def _payload_codecs() -> PayloadCodecRegistry:
    return PayloadCodecRegistry(
        {
            "pulse_program": PayloadCodec(
                id=_CODEC_ID,
                version=_CODEC_VERSION,
                media_type=_MEDIA_TYPE,
                encoder=_unused_payload_encoder,
                decoder=_identity_payload_decoder,
            )
        }
    )


def _unused_payload_encoder(_value: object) -> bytes:
    return b""


def _identity_payload_decoder(content: bytes) -> object:
    return content


def _payload_object_path(
    runtime: LocalDaemonRuntime,
    content_hash: str,
) -> Path:
    hexdigest = content_hash.removeprefix("sha256:")
    return runtime.state_dir / "objects" / hexdigest[:2] / hexdigest[2:]


def _selected_ids(context: InstrumentProviderContext) -> Sequence[str]:
    return context.instrument_ids or tuple(
        item.id for item in context.config.instrument_registry.instruments
    )
