from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Never, override

import httpx2
import pytest
from fastapi.testclient import TestClient
from scopecat.api.lab import LabClient
from scopecat.application import LabApplication
from scopecat.control.models import ResourceKey, RunPlanSummary
from scopecat.daemon.client import DaemonClient, DaemonConflictError
from scopecat.daemon.wire import (
    ExecutorStartRequest,
    InstrumentSessionApplyCommand,
    InstrumentSessionCollectCommand,
    InstrumentSessionEndCommand,
    InstrumentSessionOpenCommand,
    InstrumentSessionReadCommand,
    RunSubmission,
)
from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import (
    CollectCommand,
    CollectProductRequest,
    CollectReceipt,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateCommandField,
)
from tests.testkit.instrument_drivers import SignalInstrumentDriver, load_config

from scopecat_server import LocalDaemonRuntime


class _TrackingDriver(SignalInstrumentDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.closed = False
        self.aborted = False
        self.close_count = 0
        self.abort_count = 0

    @override
    def close(self) -> None:
        self.closed = True
        self.close_count += 1

    @override
    def abort(self) -> None:
        self.aborted = True
        self.abort_count += 1


class _TrackingProvider:
    provider_id = "tests.interactive_provider"

    def __init__(
        self,
        driver_type: type[_TrackingDriver] = _TrackingDriver,
    ) -> None:
        self._driver_type = driver_type
        self.drivers: list[_TrackingDriver] = []

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                self._driver_type(instrument_id).describe()
                for instrument_id in _selected_ids(context)
            ),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        drivers = tuple(
            self._driver_type(instrument_id) for instrument_id in _selected_ids(context)
        )
        self.drivers.extend(drivers)
        return InstrumentProviderResult(drivers=drivers)


class _SlowProvider(_TrackingProvider):
    def __init__(self, delay_seconds: float) -> None:
        super().__init__()
        self._delay_seconds = delay_seconds

    @override
    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        sleep(self._delay_seconds)
        return super().provide(context)


class _SlowRejectedProvider(_SlowProvider):
    @override
    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        result = super().provide(context)
        return InstrumentProviderResult(
            drivers=result.drivers,
            problems=(
                problem(
                    "slow_rejection",
                    "the provider rejected the connection",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_provider"),
                ),
            ),
        )


class _ReadFailDriver(_TrackingDriver):
    @override
    def read_state(self) -> Never:
        raise RuntimeError("read transport failed")


class _InvalidCollectDriver(_TrackingDriver):
    @override
    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_commands.append(command)
        return CollectReceipt(
            readback=InstrumentReadback(
                values={"signal": Quantity(value=1.0, unit="K")}
            )
        )


class _StatefulDriver(_TrackingDriver):
    def __init__(
        self,
        instrument_id: str,
        state: dict[tuple[str, str], StateValue],
    ) -> None:
        super().__init__(instrument_id)
        self._state = state


class _StatefulProvider:
    provider_id = "tests.stateful_interactive_provider"

    def __init__(self) -> None:
        self.state: dict[tuple[str, str], StateValue] = {}

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                _StatefulDriver(instrument_id, self.state).describe()
                for instrument_id in _selected_ids(context)
            ),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        return InstrumentProviderResult(
            drivers=tuple(
                _StatefulDriver(instrument_id, self.state)
                for instrument_id in _selected_ids(context)
            )
        )


class _ProblemProvider(_TrackingProvider):
    @override
    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        description = super().describe(context)
        return InstrumentProviderDescription(
            provider_id=description.provider_id,
            instruments=description.instruments,
            problems=(
                problem(
                    "source_zero_problem",
                    "source zero is misconfigured",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_provider"),
                    details={"instrument_id": "source-0"},
                ),
                problem(
                    "source_one_problem",
                    "source one is misconfigured",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location(
                        "instrument_provider",
                        "config",
                        "system",
                        "instrument_registry",
                        "instruments",
                        1,
                    ),
                ),
                problem(
                    "provider_global_problem",
                    "provider discovery is incomplete",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_provider"),
                ),
            ),
        )


def test_notebook_direct_interaction_owns_and_releases_driver(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            lab = LabClient(daemon, operator="default-operator")

            [available] = lab.instruments.list().items
            assert available.availability == "available"

            with lab.instruments.open("source-0", actor="alice") as instrument:
                description = instrument.describe()
                state_receipt = instrument.apply(
                    "set_frequency",
                    operation_id="notebook-apply-1",
                    frequency=Quantity(value=5.1, unit="GHz"),
                )
                collect_receipt = instrument.collect(
                    "scalar_signal",
                    "signal",
                    operation_id="notebook-collect-1",
                )
                [owned] = lab.instruments.list().items

                assert description.instrument_id == "source-0"
                assert state_receipt.status == "applied"
                assert collect_receipt.status == "collected"
                assert owned.availability == "active"
                assert owned.owner_kind == "instrument_session"
                assert owned.owner_actor == "alice"

            [released] = lab.instruments.list().items
            [driver] = provider.drivers
            assert released.availability == "available"
            assert driver.closed
            assert driver.applied[0].operation_id == "notebook-apply-1"
            assert driver.collect_commands[0].operation_id == "notebook-collect-1"
            assert driver.collect_commands[0].point_index == 0
            assert driver.collect_commands[0].point_count == 1


def test_operation_retry_is_deduplicated_and_conflicting_content_is_rejected(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            lease = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-1",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            command = _apply_command(value=5.0)
            request = InstrumentSessionApplyCommand(
                lease_id=lease.lease_id,
                command=command,
            )

            first = daemon.apply_instrument_state(
                lease.session_id,
                "source-0",
                request,
            )
            second = daemon.apply_instrument_state(
                lease.session_id,
                "source-0",
                request,
            )

            assert second == first
            [driver] = provider.drivers
            assert len(driver.applied) == 1
            with pytest.raises(DaemonConflictError, match="different apply content"):
                daemon.apply_instrument_state(
                    lease.session_id,
                    "source-0",
                    InstrumentSessionApplyCommand(
                        lease_id=lease.lease_id,
                        command=_apply_command(value=5.2),
                    ),
                )
            daemon.close_instrument_session(
                lease.session_id,
                InstrumentSessionEndCommand(
                    lease_id=lease.lease_id,
                    operation_id="close-1",
                ),
            )


def test_open_retry_reuses_session_without_reprovisioning(tmp_path: Path) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            command = InstrumentSessionOpenCommand(
                operation_id="open-retry",
                actor="alice",
                instrument_ids=("source-0",),
            )

            first = daemon.open_instrument_session(command)
            second = daemon.open_instrument_session(command)

            assert second == first
            assert len(provider.drivers) == 1
            daemon.close_instrument_session(
                first.session_id,
                InstrumentSessionEndCommand(
                    lease_id=first.lease_id,
                    operation_id="close-open-retry",
                ),
            )


def test_open_refreshes_lease_after_slow_provisioning(tmp_path: Path) -> None:
    lease_ttl = timedelta(milliseconds=300)
    provider = _SlowProvider(delay_seconds=0.22)
    with _runtime(tmp_path, provider, lease_ttl=lease_ttl) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)

            lease = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-slow",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

            assert lease.expires_at - datetime.now(UTC) > lease_ttl * 2 / 3
            daemon.close_instrument_session(
                lease.session_id,
                InstrumentSessionEndCommand(
                    lease_id=lease.lease_id,
                    operation_id="close-slow",
                ),
            )


def test_slow_rejection_quarantines_an_expired_session(tmp_path: Path) -> None:
    provider = _SlowRejectedProvider(delay_seconds=0.22)
    with (
        _runtime(
            tmp_path,
            provider,
            lease_ttl=timedelta(milliseconds=150),
        ) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)

        with pytest.raises(
            DaemonConflictError,
            match="lease expired while connecting",
        ):
            daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-slow-rejected",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

        [session] = runtime.application.executor._control.list_instrument_sessions()
        assert session.state == "attention_required"
        [driver] = provider.drivers
        assert driver.close_count == 1


def test_notebook_open_retry_reuses_operation_after_response_loss(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/instrument-sessions",
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
                operation_id="open-after-loss",
            )

            state = handle.read_state()
            handle.close(operation_id="close-after-open-loss")

            assert state.instrument_id == "source-0"
            assert len(provider.drivers) == 1


def test_abort_retry_replays_receipt_without_repeating_driver_calls(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            lease = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-abort-retry",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            command = InstrumentSessionEndCommand(
                lease_id=lease.lease_id,
                operation_id="abort-retry",
            )

            first = daemon.abort_instrument_session(lease.session_id, command)
            second = daemon.abort_instrument_session(lease.session_id, command)

            assert second == first
            [driver] = provider.drivers
            assert driver.abort_count == 1
            assert driver.close_count == 1
            with pytest.raises(
                DaemonConflictError,
                match="different content",
            ):
                daemon.close_instrument_session(lease.session_id, command)


def test_notebook_close_remains_retryable_after_both_transport_attempts_fail(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/close",
                drop_response_count=2,
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
            )
            handle.read_state()

            with pytest.raises(httpx2.ReadError, match="response was lost"):
                handle.close(operation_id="close-after-loss")
            receipt = handle.close()

            assert receipt is not None
            assert receipt.operation_id == "close-after-loss"
            [driver] = provider.drivers
            assert driver.close_count == 1


def test_failed_notebook_close_keeps_heartbeating_until_later_retry(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    lease_ttl = timedelta(milliseconds=120)
    heartbeat_requests = 0

    def observe_request(request: httpx2.Request) -> None:
        nonlocal heartbeat_requests
        if request.url.path.endswith("/heartbeat"):
            heartbeat_requests += 1

    with _runtime(tmp_path, provider, lease_ttl=lease_ttl) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                fail_request_suffix="/close",
                fail_request_count=2,
                observe_request=observe_request,
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
            )
            handle.read_state()

            with pytest.raises(httpx2.ReadError, match="request failed"):
                handle.close(operation_id="close-after-long-failure")
            heartbeats_before_wait = heartbeat_requests
            sleep(lease_ttl.total_seconds() * 3)

            assert heartbeat_requests > heartbeats_before_wait
            receipt = handle.close()

            assert receipt is not None
            assert receipt.operation_id == "close-after-long-failure"
            [driver] = provider.drivers
            assert driver.close_count == 1


def test_notebook_default_apply_retries_with_same_operation_after_response_loss(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/state/apply",
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
            )

            receipt = handle.apply(
                "set_frequency",
                frequency=Quantity(value=5.1, unit="GHz"),
            )
            handle.close()

            assert receipt.status == "applied"
            [driver] = provider.drivers
            assert len(driver.applied) == 1
            assert driver.applied[0].operation_id is not None


def test_notebook_default_collect_retries_with_same_operation_after_response_loss(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/collect",
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
            )

            receipt = handle.collect("scalar_signal", "signal")
            handle.close()

            assert receipt.status == "collected"
            [driver] = provider.drivers
            assert len(driver.collect_commands) == 1
            assert driver.collect_commands[0].operation_id is not None


def test_read_failure_keeps_session_active_and_does_not_quarantine(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_ReadFailDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            lease = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-read-failure",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

            with pytest.raises(DaemonConflictError, match="state read failed"):
                daemon.read_instrument_state(
                    lease.session_id,
                    "source-0",
                    InstrumentSessionReadCommand(lease_id=lease.lease_id),
                )

            [instrument] = daemon.list_instruments().items
            assert instrument.availability == "active"
            daemon.close_instrument_session(
                lease.session_id,
                InstrumentSessionEndCommand(
                    lease_id=lease.lease_id,
                    operation_id="close-read-failure",
                ),
            )


def test_invalid_collect_receipt_is_deduplicated_without_quarantining(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_InvalidCollectDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            lease = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-invalid-collect",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            request = InstrumentSessionCollectCommand(
                lease_id=lease.lease_id,
                command=CollectCommand(
                    operation_id="collect-invalid",
                    instrument_id="source-0",
                    point_index=0,
                    point_count=1,
                    requests=[
                        CollectProductRequest(
                            id="signal",
                            capability_id="scalar_signal",
                            dtype="float64",
                            unit="ratio",
                        )
                    ],
                ),
            )

            for _attempt in range(2):
                with pytest.raises(
                    DaemonConflictError,
                    match="unit_mismatch",
                ):
                    daemon.collect_instrument(
                        lease.session_id,
                        "source-0",
                        request,
                    )

            [driver] = provider.drivers
            [instrument] = daemon.list_instruments().items
            assert len(driver.collect_commands) == 1
            assert instrument.availability == "active"
            daemon.close_instrument_session(
                lease.session_id,
                InstrumentSessionEndCommand(
                    lease_id=lease.lease_id,
                    operation_id="close-invalid-collect",
                ),
            )


def test_provider_instance_and_virtual_state_survive_across_sessions(
    tmp_path: Path,
) -> None:
    build_count = 0

    def factory(_root: Path) -> LabApplication:
        def build_system(_config: ConfigProfileSnapshot) -> ExperimentSystem:
            nonlocal build_count
            build_count += 1
            return ExperimentSystem(provider=_StatefulProvider())

        return LabApplication(build_system=build_system)

    with (
        LocalDaemonRuntime(
            tmp_path,
            bootstrap_config=load_config(),
            application_factory=factory,
        ) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        first = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-stateful-1",
                actor="alice",
                instrument_ids=("source-0",),
            )
        )
        daemon.apply_instrument_state(
            first.session_id,
            "source-0",
            InstrumentSessionApplyCommand(
                lease_id=first.lease_id,
                command=_apply_command(value=5.1),
            ),
        )
        daemon.close_instrument_session(
            first.session_id,
            InstrumentSessionEndCommand(
                lease_id=first.lease_id,
                operation_id="close-stateful-1",
            ),
        )

        second = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-stateful-2",
                actor="alice",
                instrument_ids=("source-0",),
            )
        )
        state = daemon.read_instrument_state(
            second.session_id,
            "source-0",
            InstrumentSessionReadCommand(lease_id=second.lease_id),
        )
        daemon.close_instrument_session(
            second.session_id,
            InstrumentSessionEndCommand(
                lease_id=second.lease_id,
                operation_id="close-stateful-2",
            ),
        )

    [field] = state.fields
    assert field.value == StateValue(Quantity(value=5.1, unit="GHz"))
    assert build_count == 1


def test_provider_problems_are_scoped_without_polluting_healthy_views(
    tmp_path: Path,
) -> None:
    config = _two_instrument_config()
    provider = _ProblemProvider()
    with _runtime(tmp_path, provider, config=config) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            instruments = _daemon_client(transport).list_instruments()

    by_id = {item.spec.id: item for item in instruments.items}
    assert [item.code for item in by_id["source-0"].problems] == ["source_zero_problem"]
    assert [item.code for item in by_id["source-1"].problems] == ["source_one_problem"]
    assert [item.code for item in instruments.problems] == ["provider_global_problem"]


def test_run_and_interactive_session_compete_for_the_same_resource(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    config = load_config()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            lease = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-exclusive",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            admission = daemon.submit_run(_submission(config))

            with pytest.raises(DaemonConflictError, match="resources are busy"):
                daemon.start_executor(
                    admission.run_id,
                    ExecutorStartRequest(executor_id="notebook"),
                )

            daemon.close_instrument_session(
                lease.session_id,
                InstrumentSessionEndCommand(
                    lease_id=lease.lease_id,
                    operation_id="close-exclusive",
                ),
            )
            executor = daemon.start_executor(
                admission.run_id,
                ExecutorStartRequest(executor_id="notebook"),
            )
            assert executor.run_id == admission.run_id

            with pytest.raises(DaemonConflictError, match="resources are busy"):
                daemon.open_instrument_session(
                    InstrumentSessionOpenCommand(
                        operation_id="open-while-run",
                        actor="bob",
                        instrument_ids=("source-0",),
                    )
                )


def _runtime(
    root: Path,
    provider: _TrackingProvider,
    *,
    config: ConfigProfileSnapshot | None = None,
    lease_ttl: timedelta | None = None,
) -> LocalDaemonRuntime:
    def factory(_root: Path) -> LabApplication:
        return LabApplication(
            build_system=lambda _config: ExperimentSystem(provider=provider)
        )

    return LocalDaemonRuntime(
        root,
        bootstrap_config=config if config is not None else load_config(),
        application_factory=factory,
        lease_ttl=lease_ttl,
    )


def _daemon_client(
    transport: TestClient,
    *,
    drop_response_suffix: str | None = None,
    drop_response_count: int = 1,
    fail_request_suffix: str | None = None,
    fail_request_count: int = 0,
    observe_request: Callable[[httpx2.Request], None] | None = None,
) -> DaemonClient:
    responses_dropped = 0
    requests_failed = 0

    def send(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests_failed, responses_dropped
        if observe_request is not None:
            observe_request(request)
        if (
            fail_request_suffix is not None
            and request.url.path.endswith(fail_request_suffix)
            and requests_failed < fail_request_count
        ):
            requests_failed += 1
            raise httpx2.ReadError(
                "request failed before reaching the daemon",
                request=request,
            )
        response = transport.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        translated = httpx2.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )
        if (
            drop_response_suffix is not None
            and request.url.path.endswith(drop_response_suffix)
            and responses_dropped < drop_response_count
        ):
            responses_dropped += 1
            raise httpx2.ReadError(
                "response was lost",
                request=request,
            )
        return translated

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )


def _selected_ids(context: InstrumentProviderContext) -> Sequence[str]:
    return context.instrument_ids or tuple(
        item.id for item in context.config.instrument_registry.instruments
    )


def _apply_command(*, value: float) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        operation_id="apply-1",
        instrument_id="source-0",
        fields=[
            InstrumentStateCommandField(
                resource_id="source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=StateValue(Quantity(value=value, unit="GHz")),
            )
        ],
    )


def _two_instrument_config() -> ConfigProfileSnapshot:
    config = load_config()
    [source] = config.instrument_registry.instruments
    registry = config.instrument_registry.model_copy(
        update={
            "instruments": [
                source,
                source.model_copy(update={"id": "source-1"}),
            ]
        }
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        }
    )


def _submission(config: ConfigProfileSnapshot) -> RunSubmission:
    return RunSubmission(
        submission_id="interactive-exclusion",
        config=config,
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            run_resource_claims=(ResourceKey(kind="instrument", id="source-0"),),
        ),
    )
