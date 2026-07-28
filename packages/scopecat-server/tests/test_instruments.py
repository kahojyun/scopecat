from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
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
    InstrumentSessionOpenCommand,
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
    CollectReceipt,
    CollectResultRequest,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentReadback,
    InstrumentStateAssignment,
    InstrumentStateCommand,
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


class _RejectedProvider(_TrackingProvider):
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
                    "test.set_frequency/v1",
                    operation_id="notebook-apply-1",
                    frequency=Quantity(value=5.1, unit="GHz"),
                )
                collect_receipt = instrument.collect(
                    "test.scalar_signal/v1",
                    "sample",
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
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-1",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            command = _apply_command(value=5.0)

            first = daemon.apply_instrument_state(
                session.session_id,
                "source-0",
                command,
            )
            second = daemon.apply_instrument_state(
                session.session_id,
                "source-0",
                command,
            )

            assert second == first
            [driver] = provider.drivers
            assert len(driver.applied) == 1
            with pytest.raises(DaemonConflictError, match="different apply content"):
                daemon.apply_instrument_state(
                    session.session_id,
                    "source-0",
                    _apply_command(value=5.2),
                )
            daemon.close_instrument_session(session.session_id)


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
            daemon.close_instrument_session(first.session_id)


def test_provider_rejection_closes_the_daemon_session(tmp_path: Path) -> None:
    provider = _RejectedProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)

        with pytest.raises(DaemonConflictError, match="provider rejected"):
            daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-rejected",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

        [session] = runtime.application.executor._control.list_instrument_sessions()
        assert session.state == "closed"
        assert session.end_status == "aborted"
        [instrument] = daemon.list_instruments().items
        assert instrument.availability == "available"
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
            handle.close()

            assert state.instrument_id == "source-0"
            assert len(provider.drivers) == 1


def test_notebook_can_abort_a_daemon_owned_session_by_id(tmp_path: Path) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))
            handle = lab.instruments.open("source-0", actor="alice")
            handle.read_state()

            receipt = lab.instruments.abort_session(handle.session_id)
            replay = handle.abort()

            assert receipt.status == "aborted"
            assert replay == receipt
            [driver] = provider.drivers
            assert driver.abort_count == 1


def test_abort_retry_replays_receipt_without_repeating_driver_calls(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-abort-retry",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            first = daemon.abort_instrument_session(session.session_id)
            second = daemon.abort_instrument_session(session.session_id)

            assert second == first
            [driver] = provider.drivers
            assert driver.abort_count == 1
            assert driver.close_count == 1
            assert daemon.close_instrument_session(session.session_id) == first


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
                handle.close()
            receipt = handle.close()

            assert receipt is not None
            assert receipt.status == "closed"
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
                "test.set_frequency/v1",
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

            receipt = handle.collect(
                "test.scalar_signal/v1",
                "sample",
                "signal",
            )
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
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-read-failure",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

            with pytest.raises(DaemonConflictError, match="state read failed"):
                daemon.read_instrument_state(
                    session.session_id,
                    "source-0",
                )

            [instrument] = daemon.list_instruments().items
            assert instrument.availability == "active"
            daemon.close_instrument_session(session.session_id)


def test_invalid_collect_receipt_is_deduplicated_without_quarantining(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_InvalidCollectDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-invalid-collect",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            request = CollectCommand(
                operation_id="collect-invalid",
                instrument_id="source-0",
                point_index=0,
                point_count=1,
                requests=[
                    CollectResultRequest(
                        id="signal",
                        interface_id="test.scalar_signal/v1",
                        acquisition_id="sample",
                        result_id="signal",
                        dtype="float64",
                        unit="ratio",
                    )
                ],
            )

            for _attempt in range(2):
                with pytest.raises(
                    DaemonConflictError,
                    match="unit_mismatch",
                ):
                    daemon.collect_instrument(
                        session.session_id,
                        "source-0",
                        request,
                    )

            [driver] = provider.drivers
            [instrument] = daemon.list_instruments().items
            assert len(driver.collect_commands) == 1
            assert instrument.availability == "active"
            daemon.close_instrument_session(session.session_id)


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
            _apply_command(value=5.1),
        )
        daemon.close_instrument_session(first.session_id)

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
        )
        daemon.close_instrument_session(second.session_id)

    [property_state] = state.properties
    assert property_state.value == StateValue(Quantity(value=5.1, unit="GHz"))
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
            session = daemon.open_instrument_session(
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

            daemon.close_instrument_session(session.session_id)
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
) -> LocalDaemonRuntime:
    def factory(_root: Path) -> LabApplication:
        return LabApplication(
            build_system=lambda _config: ExperimentSystem(provider=provider)
        )

    return LocalDaemonRuntime(
        root,
        bootstrap_config=config if config is not None else load_config(),
        application_factory=factory,
    )


def _daemon_client(
    transport: TestClient,
    *,
    drop_response_suffix: str | None = None,
    drop_response_count: int = 1,
) -> DaemonClient:
    responses_dropped = 0

    def send(request: httpx2.Request) -> httpx2.Response:
        nonlocal responses_dropped
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
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.set_frequency/v1",
                property_id="frequency",
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
