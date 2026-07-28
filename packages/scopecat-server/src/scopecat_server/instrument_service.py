"""Daemon-owned drivers for direct sessions and admitted experiment runs."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from threading import RLock
from typing import Literal

from pydantic import JsonValue
from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    ExecutorLeaseNotHeld,
    InstrumentSessionNotActive,
    SQLiteControlPlane,
    SQLiteRunRepository,
)
from scopecat.control.models import (
    DurableEventInput,
    InstrumentSession,
    ResourceClaim,
)
from scopecat.daemon.views import InstrumentListView, InstrumentView
from scopecat.daemon.wire import (
    InstrumentSessionEndReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
)
from scopecat.execution.ports.instruments import (
    RunHardwareApply,
    RunHardwareBatchReceipt,
    RunHardwareCollect,
    RunHardwareFinalizationReceipt,
    RunHardwareInvoke,
    RunHardwareValue,
)
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    RuntimeLocation,
    problem,
)
from scopecat.planning.provider_validation import (
    describe_instruments,
    instrument_contract_fingerprint,
    validate_instruments,
)
from scopecat.planning.system import ExperimentSystem, ExperimentSystemBuilder
from scopecat.records.artifact import CommandPayload
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentSpec,
    config_content_hash,
)
from scopecat.records.instrument import (
    InstrumentStateSnapshot,
    property_target_identity,
)
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InvokeCommand,
    InvokeReceipt,
    apply_state_command_to_snapshot,
    validate_collect_command,
    validate_collect_receipt,
    validate_invoke_command,
    validate_state_command,
)
from scopecat.sdk.payloads import PayloadCodecRegistry

from .config_service import ConfigService
from .errors import BackendConflict, BackendNotFound
from .payload_service import CommandPayloadService

_FINISHED_RUN_CACHE_LIMIT = 256


@dataclass(slots=True)
class _OperationLedger:
    apply_receipts: dict[str, tuple[InstrumentStateCommand, ApplyReceipt]] = field(
        default_factory=dict
    )
    invoke_receipts: dict[str, tuple[InvokeCommand, InvokeReceipt]] = field(
        default_factory=dict
    )
    collect_receipts: dict[str, tuple[CollectCommand, CollectReceipt]] = field(
        default_factory=dict
    )
    collect_failures: dict[str, tuple[CollectCommand, str]] = field(
        default_factory=dict
    )


@dataclass(slots=True)
class _LiveDrivers:
    drivers: dict[str, InstrumentDriver]
    descriptions: dict[str, InstrumentDescription]
    payload_codecs: PayloadCodecRegistry
    ledger: _OperationLedger = field(default_factory=_OperationLedger)
    assumed_states: dict[str, InstrumentStateSnapshot] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock)

    @property
    def apply_receipts(
        self,
    ) -> dict[str, tuple[InstrumentStateCommand, ApplyReceipt]]:
        return self.ledger.apply_receipts

    @property
    def collect_receipts(self) -> dict[str, tuple[CollectCommand, CollectReceipt]]:
        return self.ledger.collect_receipts

    @property
    def invoke_receipts(self) -> dict[str, tuple[InvokeCommand, InvokeReceipt]]:
        return self.ledger.invoke_receipts

    @property
    def collect_failures(self) -> dict[str, tuple[CollectCommand, str]]:
        return self.ledger.collect_failures


@dataclass(frozen=True, slots=True)
class _FinishedRunHardware:
    command: RunHardwareFinishCommand
    receipt: RunHardwareFinalizationReceipt


@dataclass(frozen=True, slots=True)
class _RunProvision:
    command: RunInstrumentProvisionCommand
    receipt: RunInstrumentProvisionReceipt
    batches: dict[
        str,
        tuple[RunHardwareBatchCommand, RunHardwareBatchReceipt],
    ] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock, compare=False, repr=False)


class InstrumentService:
    """Own live drivers and serialize direct and run-scoped operations."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        config: ConfigService,
        build_system: ExperimentSystemBuilder | None,
        payloads: CommandPayloadService,
    ) -> None:
        self._control = control
        self._runs = runs
        self._config = config
        self._build_system = build_system
        self._payloads = payloads
        self._sessions: dict[str, _LiveDrivers] = {}
        self._finished_runs: OrderedDict[str, _FinishedRunHardware] = OrderedDict()
        self._finished_run_cache_limit = _FINISHED_RUN_CACHE_LIMIT
        self._run_runtimes: dict[str, _LiveDrivers] = {}
        self._run_provisions: dict[str, _RunProvision] = {}
        self._sessions_lock = RLock()
        self._open_lock = RLock()
        self._run_lock = RLock()
        self._run_open_locks: dict[str, RLock] = {}
        self._finalizing_runs: set[str] = set()
        self._attention_lock = RLock()
        self._provider_lock = RLock()
        self._system_content_hash: str | None = None
        self._cached_system: ExperimentSystem | None = None

    def list_instruments(self) -> InstrumentListView:
        active = self._config.get_active_config()
        descriptions, provider_problems = self._descriptions(active.config)
        global_problems, instrument_problems = _scope_provider_problems(
            active.config.instrument_registry.instruments,
            provider_problems,
        )
        with self._control.transaction() as connection:
            claims = {
                claim.resource.id: claim
                for claim in self._control.list_resource_claims_in_transaction(
                    connection
                )
                if claim.resource.kind == "instrument"
            }
        session_actors = {
            session.session_id: session.actor
            for session in self._control.list_instrument_sessions()
            if session.state != "closed"
        }
        items = tuple(
            self._instrument_view(
                spec,
                description=descriptions.get(spec.id),
                claim=claims.get(spec.id),
                owner_actor=(
                    session_actors.get(claim.owner_id)
                    if (
                        (claim := claims.get(spec.id)) is not None
                        and claim.owner_kind == "instrument_session"
                    )
                    else None
                ),
                problems=instrument_problems.get(spec.id, ()),
            )
            for spec in active.config.instrument_registry.instruments
        )
        return InstrumentListView(
            config_entry_id=active.entry.id,
            config_content_hash=active.entry.content_hash,
            items=items,
            problems=global_problems,
        )

    def get_instrument(self, instrument_id: str) -> InstrumentView:
        instruments = self.list_instruments()
        for item in instruments.items:
            if item.spec.id == instrument_id:
                return item
        raise BackendNotFound(f"instrument was not found: {instrument_id}")

    def authorize_session_payload_upload(self, session_id: str) -> None:
        """Require an active daemon-owned session before accepting bytes."""

        try:
            self._control.validate_instrument_session(session_id)
            self._live_runtime(session_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error

    def authorize_run_payload_upload(self, run_id: str, lease_id: str) -> None:
        """Fence a run-scoped upload with the current executor lease."""

        with self._run_operation_lock(run_id):
            self._fence_run(run_id, lease_id)

    def provision_run(
        self,
        run_id: str,
        command: RunInstrumentProvisionCommand,
    ) -> RunInstrumentProvisionReceipt:
        """Connect the exact instrument claims admitted with one fenced run."""

        with self._run_operation_lock(run_id):
            return self._provision_run(run_id, command)

    def _provision_run(
        self,
        run_id: str,
        command: RunInstrumentProvisionCommand,
    ) -> RunInstrumentProvisionReceipt:
        self._fence_run(run_id, command.lease_id)
        self._require_provisionable_run(run_id)
        cached = self._run_provision_state(run_id)
        if cached is not None:
            if cached.command != command:
                if cached.command.operation_id == command.operation_id:
                    raise BackendConflict(
                        "run instrument provision operation id has different content"
                    )
                raise BackendConflict("run instruments are already provisioned")
            return cached.receipt

        try:
            control_run = self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        instrument_claims = frozenset(
            claim.id
            for claim in control_run.admission.resource_claims
            if claim.kind == "instrument"
        )
        instrument_ids = control_run.admission.plan.host_instrument_order
        if not instrument_ids:
            receipt = RunInstrumentProvisionReceipt(
                run_id=run_id,
                operation_id=command.operation_id,
                status="ready",
            )
            self._store_run_provision(
                run_id,
                _RunProvision(
                    command=command,
                    receipt=receipt,
                    lock=self._run_operation_lock(run_id),
                ),
            )
            return receipt

        config = self._runs.read_config_profile_snapshot(run_id)
        try:
            system = self._system(config)
            provider = self._provider(config)
        except Exception as error:
            return self._reject_run_provision(
                run_id,
                command,
                problems=(
                    _provision_problem(
                        (
                            "instrument_provider_unavailable"
                            if isinstance(error, BackendConflict)
                            else "instrument_provider_construction_failed"
                        ),
                        "instrument provider could not be constructed",
                        run_id=run_id,
                        operation_id=command.operation_id,
                        details={"exception_type": type(error).__name__},
                    ),
                ),
            )
        provider_id = provider.provider_id

        try:
            provider_description = provider.describe(
                InstrumentProviderContext(
                    config=config,
                    instrument_ids=instrument_ids,
                )
            )
        except Exception:
            return self._reject_run_provision(
                run_id,
                command,
                problems=(
                    _provision_problem(
                        "instrument_provider_description_failed",
                        "instrument provider description failed",
                        run_id=run_id,
                        operation_id=command.operation_id,
                    ),
                ),
            )
        global_problems, instrument_problems = _scope_provider_problems(
            config.instrument_registry.instruments,
            provider_description.problems,
        )
        setup_problems = list(global_problems)
        setup_problems.extend(
            item
            for instrument_id in instrument_ids
            for item in instrument_problems.get(instrument_id, ())
        )
        if provider_description.provider_id != provider_id:
            setup_problems.append(
                _provision_problem(
                    "instrument_provider_id_mismatch",
                    "instrument provider description changed provider identity",
                    run_id=run_id,
                    operation_id=command.operation_id,
                )
            )
        advertised = {
            description.instrument_id: description
            for description in provider_description.instruments
            if description.instrument_id in instrument_claims
        }
        missing = tuple(
            instrument_id
            for instrument_id in instrument_ids
            if instrument_id not in advertised
        )
        setup_problems.extend(
            _provision_problem(
                "instrument_claim_not_described",
                f"instrument provider does not describe admitted claim {instrument_id}",
                run_id=run_id,
                operation_id=command.operation_id,
                instrument_id=instrument_id,
            )
            for instrument_id in missing
        )
        if provider_id != control_run.admission.plan.host_provider_id:
            setup_problems.append(
                _provision_problem(
                    "instrument_provider_changed_after_admission",
                    "instrument provider differs from the admitted contract",
                    run_id=run_id,
                    operation_id=command.operation_id,
                )
            )
        if not missing:
            descriptions = tuple(advertised[item] for item in instrument_ids)
            if (
                instrument_contract_fingerprint(provider_id, descriptions)
                != control_run.admission.plan.host_contract_fingerprint
            ):
                setup_problems.append(
                    _provision_problem(
                        "instrument_contract_changed_after_admission",
                        "instrument descriptions differ from the admitted contract",
                        run_id=run_id,
                        operation_id=command.operation_id,
                    )
                )
        if setup_problems:
            return self._reject_run_provision(
                run_id,
                command,
                problems=tuple(setup_problems),
            )

        try:
            runtime, metadata = _provide_drivers(
                provider,
                config=config,
                instrument_ids=instrument_ids,
                expected=advertised,
                payload_codecs=system.payload_codecs,
            )
        except _ProvisioningRejected as error:
            if _call_all(error.drivers, _close_driver):
                self._mark_run_unknown(
                    run_id,
                    token=command.lease_id,
                    reason="run_instrument_provisioning_cleanup_failed",
                )
                raise BackendConflict(
                    "instrument provisioning rejection could not be released"
                ) from error
            return self._reject_run_provision(
                run_id,
                command,
                problems=error.problems,
            )
        except _ProvisioningUnknown as error:
            _call_all(error.drivers, _abort_driver)
            _call_all(error.drivers, _close_driver)
            self._mark_run_unknown(
                run_id,
                token=command.lease_id,
                reason="run_instrument_provisioning_unknown",
            )
            raise BackendConflict(
                "instrument provider failed while connecting"
            ) from error

        try:
            initial_state = tuple(
                _read_driver_state(
                    runtime.drivers[instrument_id],
                    instrument_id=instrument_id,
                )
                for instrument_id in instrument_ids
            )
        except BackendConflict as error:
            if _call_all(runtime.drivers.values(), _close_driver):
                self._mark_run_unknown(
                    run_id,
                    token=command.lease_id,
                    reason="run_instrument_initial_read_cleanup_failed",
                )
                raise BackendConflict(
                    "instrument initial readback could not be released"
                ) from error
            return self._reject_run_provision(
                run_id,
                command,
                problems=(
                    _provision_problem(
                        "instrument_initial_read_failed",
                        "instrument initial state could not be read",
                        run_id=run_id,
                        operation_id=command.operation_id,
                    ),
                ),
            )
        runtime.assumed_states = {
            state.instrument_id: state.model_copy(deep=True) for state in initial_state
        }

        try:
            self._record_run_operation_event(
                run_id,
                token=command.lease_id,
                instrument_id=None,
                operation_id=command.operation_id,
                event_kind="run_instruments_provisioned",
                status="ready",
            )
        except BackendConflict:
            _call_all(runtime.drivers.values(), _abort_driver)
            _call_all(runtime.drivers.values(), _close_driver)
            self._mark_run_unknown(
                run_id,
                token=command.lease_id,
                reason="run_instrument_provisioning_fence_lost",
            )
            raise

        receipt = RunInstrumentProvisionReceipt(
            run_id=run_id,
            operation_id=command.operation_id,
            status="ready",
            instrument_ids=instrument_ids,
            metadata=metadata,
            initial_state=initial_state,
        )
        provision = _RunProvision(
            command=command,
            receipt=receipt,
            lock=self._run_operation_lock(run_id),
        )
        self._store_run_provision(run_id, provision, runtime=runtime)
        return receipt

    def _require_provisionable_run(self, run_id: str) -> None:
        with self._run_lock:
            if run_id in self._finished_runs:
                raise BackendConflict("run hardware is already finalized")
        if self._run_is_finalizing(run_id):
            raise BackendConflict("run instrument host is finalizing")

    def _reject_run_provision(
        self,
        run_id: str,
        command: RunInstrumentProvisionCommand,
        *,
        problems: tuple[Problem, ...],
    ) -> RunInstrumentProvisionReceipt:
        receipt = RunInstrumentProvisionReceipt(
            run_id=run_id,
            operation_id=command.operation_id,
            status="rejected",
            problems=problems,
        )
        self._store_run_provision(
            run_id,
            _RunProvision(
                command=command,
                receipt=receipt,
                lock=self._run_operation_lock(run_id),
            ),
        )
        return receipt

    def execute_run_hardware(
        self,
        run_id: str,
        request: RunHardwareBatchCommand,
    ) -> RunHardwareBatchReceipt:
        """Execute one idempotent ordered hardware block under the run fence."""

        with self._run_operation_lock(run_id):
            self._fence_run(run_id, request.lease_id)
            provision = self._run_provision_state(run_id)
            if provision is None or provision.receipt.status != "ready":
                raise BackendConflict("run hardware is not ready")
            runtime = self._run_runtime_state(run_id)
            if runtime is None:
                raise BackendConflict("run has no live daemon instrument drivers")
            preflight_problems = self._preflight_hardware_batch(
                run_id,
                runtime,
                request,
            )
            if preflight_problems:
                return RunHardwareBatchReceipt(
                    operation_id=request.batch.operation_id,
                    problems=preflight_problems,
                )
            canonical_request = self._payloads.canonicalize_hardware_command(request)
            cached = provision.batches.get(canonical_request.batch.operation_id)
            if cached is not None:
                cached_request, cached_receipt = cached
                if cached_request != canonical_request:
                    raise BackendConflict(
                        "hardware batch id has different operation content"
                    )
                return cached_receipt
            driver_request = self._payloads.materialize_hardware_command(
                canonical_request
            )
            batch_evidence = canonical_request.batch.model_dump(
                mode="json",
                exclude={
                    "actions": {
                        "__all__": {
                            "payloads": {"__all__": {"body"}},
                        }
                    }
                },
            )
            self._record_run_operation_event(
                run_id,
                token=canonical_request.lease_id,
                instrument_id=None,
                operation_id=canonical_request.batch.operation_id,
                event_kind="run_hardware_batch_started",
                status=None,
                details={"batch": batch_evidence},
            )
            values: list[RunHardwareValue] = []
            problems: list[Problem] = []
            completed_effect_ids: list[str] = []
            effect_receipts: list[JsonValue] = []
            with runtime.lock:
                for action in driver_request.batch.actions:
                    try:
                        if isinstance(action, RunHardwareApply):
                            evidence = self._execute_hardware_apply(
                                run_id,
                                canonical_request.lease_id,
                                runtime,
                                action,
                            )
                        elif isinstance(action, RunHardwareInvoke):
                            evidence = self._execute_hardware_invoke(
                                run_id,
                                canonical_request.lease_id,
                                runtime,
                                action,
                            )
                        else:
                            collected, evidence = self._execute_hardware_collect(
                                run_id,
                                canonical_request.lease_id,
                                runtime,
                                action,
                            )
                            values.extend(collected)
                        completed_effect_ids.append(action.effect_id)
                        effect_receipts.append(evidence)
                    except BackendConflict as error:
                        if self._run_runtime_state(run_id) is not runtime:
                            raise
                        problems.append(
                            _hardware_problem(
                                "hardware_action_failed",
                                str(error),
                                run_id=run_id,
                                operation_id=action.effect_id,
                                instrument_id=action.instrument_id,
                                point_index=action.point_index,
                            )
                        )
                        break
            receipt = RunHardwareBatchReceipt(
                operation_id=canonical_request.batch.operation_id,
                values=tuple(values),
                problems=tuple(problems),
            )
            receipt_evidence: dict[str, JsonValue] = {
                "completed_effect_ids": list(completed_effect_ids),
                "effect_receipts": effect_receipts,
                "problem_codes": [item.code for item in problems],
                "value_product_use_ids": [value.product_use_id for value in values],
            }
            try:
                self._record_run_operation_event(
                    run_id,
                    token=canonical_request.lease_id,
                    instrument_id=None,
                    operation_id=canonical_request.batch.operation_id,
                    event_kind="run_hardware_batch_finished",
                    status="failed" if problems else "completed",
                    details=receipt_evidence,
                )
            except BackendConflict:
                self._lose_run_runtime(
                    run_id,
                    runtime,
                    token=canonical_request.lease_id,
                    reason="run_hardware_batch_audit_unknown",
                )
                raise
            provision.batches[canonical_request.batch.operation_id] = (
                canonical_request,
                receipt,
            )
            return receipt

    def _preflight_hardware_batch(
        self,
        run_id: str,
        runtime: _LiveDrivers,
        request: RunHardwareBatchCommand,
    ) -> tuple[Problem, ...]:
        """Validate the complete batch before the first hardware side effect."""

        problems: list[Problem] = []
        for action in request.batch.actions:
            if (
                action.instrument_id not in runtime.drivers
                or action.instrument_id not in runtime.descriptions
                or (
                    isinstance(action, RunHardwareApply | RunHardwareInvoke)
                    and action.instrument_id not in runtime.assumed_states
                )
            ):
                problems.append(
                    _hardware_problem(
                        "hardware_instrument_not_live",
                        (
                            "instrument is not live for run "
                            f"{run_id}: {action.instrument_id}"
                        ),
                        run_id=run_id,
                        operation_id=action.effect_id,
                        instrument_id=action.instrument_id,
                        point_index=action.point_index,
                    )
                )
                continue
            if isinstance(action, RunHardwareApply):
                command = InstrumentStateCommand(
                    command_id=action.effect_id,
                    instrument_id=action.instrument_id,
                    assignments=list(action.assignments),
                )
                problems.extend(
                    validate_state_command(
                        command=command,
                        description=runtime.descriptions[action.instrument_id],
                    )
                )
            elif isinstance(action, RunHardwareInvoke):
                command = InvokeCommand(
                    command_id=action.effect_id,
                    instrument_id=action.instrument_id,
                    resource_id=action.resource_id,
                    interface_id=action.interface_id,
                    component_path=list(action.component_path),
                    operation_id=action.operation_id,
                    arguments=list(action.arguments),
                    payloads=action.payloads,
                    entity_ids=list(action.entity_ids),
                    channel_bindings=list(action.channel_bindings),
                )
                problems.extend(
                    validate_invoke_command(
                        command=command,
                        description=runtime.descriptions[action.instrument_id],
                    )
                )
                problems.extend(
                    _payload_codec_problems(
                        command.payloads,
                        runtime.payload_codecs,
                        run_id=run_id,
                        operation_id=action.effect_id,
                        instrument_id=action.instrument_id,
                        point_index=action.point_index,
                    )
                )
            else:
                command = CollectCommand(
                    command_id=action.effect_id,
                    instrument_id=action.instrument_id,
                    point_index=action.point_index,
                    point_count=action.point_count,
                    requests=list(action.requests),
                )
                problems.extend(
                    validate_collect_command(
                        command=command,
                        description=runtime.descriptions[action.instrument_id],
                    )
                )
        return tuple(problems)

    def _execute_hardware_apply(
        self,
        run_id: str,
        token: str,
        runtime: _LiveDrivers,
        action: RunHardwareApply,
    ) -> dict[str, JsonValue]:
        current = runtime.assumed_states[action.instrument_id]
        assignments = tuple(
            assignment
            for assignment in action.assignments
            if _state_value(current, assignment) != assignment.value
        )
        if not assignments:
            return {
                "effect_id": action.effect_id,
                "status": "unchanged",
                "metadata": {},
            }
        command = InstrumentStateCommand(
            command_id=action.effect_id,
            instrument_id=action.instrument_id,
            assignments=list(assignments),
        )
        _runtime, driver = self._run_driver(run_id, action.instrument_id)
        try:
            receipt = driver.apply_state(command)
        except Exception as error:
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_apply_unknown",
            )
            raise BackendConflict(
                "instrument apply failed with unknown state"
            ) from error
        if receipt.status == "unknown":
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_apply_receipt_unknown",
            )
        if receipt.status != "applied":
            raise BackendConflict(
                "; ".join(item.message for item in receipt.problems)
                or f"instrument apply returned {receipt.status}"
            )
        next_state = receipt.state or apply_state_command_to_snapshot(current, command)
        if next_state.instrument_id != action.instrument_id:
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_apply_state_mismatch",
            )
            raise BackendConflict("instrument apply returned state for another device")
        runtime.assumed_states[action.instrument_id] = next_state.model_copy(deep=True)
        return {
            "effect_id": action.effect_id,
            "status": receipt.status,
            "metadata": dict(receipt.metadata),
        }

    def _execute_hardware_invoke(
        self,
        run_id: str,
        token: str,
        runtime: _LiveDrivers,
        action: RunHardwareInvoke,
    ) -> dict[str, JsonValue]:
        command = InvokeCommand(
            command_id=action.effect_id,
            instrument_id=action.instrument_id,
            resource_id=action.resource_id,
            interface_id=action.interface_id,
            component_path=list(action.component_path),
            operation_id=action.operation_id,
            arguments=list(action.arguments),
            payloads=action.payloads,
            entity_ids=list(action.entity_ids),
            channel_bindings=list(action.channel_bindings),
        )
        _runtime, driver = self._run_driver(run_id, action.instrument_id)
        try:
            receipt = driver.invoke(command)
        except Exception as error:
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_invoke_unknown",
            )
            raise BackendConflict(
                "instrument invoke failed with unknown state"
            ) from error
        if receipt.status == "unknown":
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_invoke_receipt_unknown",
            )
        if receipt.status != "invoked":
            raise BackendConflict(
                "; ".join(item.message for item in receipt.problems)
                or f"instrument invoke returned {receipt.status}"
            )
        try:
            next_state = receipt.state or _read_driver_state(
                driver,
                instrument_id=action.instrument_id,
            )
        except Exception as error:
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_invoke_state_unknown",
            )
            raise BackendConflict(
                "instrument invoke completed but state synchronization failed"
            ) from error
        if next_state.instrument_id != action.instrument_id:
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_invoke_state_mismatch",
            )
            raise BackendConflict("instrument invoke returned state for another device")
        runtime.assumed_states[action.instrument_id] = next_state.model_copy(deep=True)
        receipt = receipt.model_copy(update={"state": next_state})
        return {
            "effect_id": action.effect_id,
            "status": receipt.status,
            "metadata": dict(receipt.metadata),
        }

    def _execute_hardware_collect(
        self,
        run_id: str,
        token: str,
        runtime: _LiveDrivers,
        action: RunHardwareCollect,
    ) -> tuple[tuple[RunHardwareValue, ...], dict[str, JsonValue]]:
        command = CollectCommand(
            command_id=action.effect_id,
            instrument_id=action.instrument_id,
            point_index=action.point_index,
            point_count=action.point_count,
            requests=list(action.requests),
        )
        _runtime, driver = self._run_driver(run_id, action.instrument_id)
        try:
            receipt = driver.collect(command)
        except Exception as error:
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_collect_unknown",
            )
            raise BackendConflict(
                "instrument collect failed with unknown state"
            ) from error
        receipt_problems = validate_collect_receipt(
            command=command,
            receipt=receipt,
        )
        if receipt_problems:
            raise BackendConflict("; ".join(item.message for item in receipt_problems))
        if receipt.status == "unknown":
            self._lose_run_runtime(
                run_id,
                runtime,
                token=token,
                reason="run_instrument_collect_receipt_unknown",
            )
        if receipt.status != "collected" or receipt.readback is None:
            raise BackendConflict(
                "; ".join(item.message for item in receipt.problems)
                or f"instrument collect returned {receipt.status}"
            )
        bindings = {
            binding.request_id: binding.product_use_ids for binding in action.bindings
        }
        if set(receipt.readback.values) != set(bindings):
            raise BackendConflict(
                "instrument acquisition results do not match hardware batch bindings"
            )
        values = tuple(
            RunHardwareValue(
                point_index=action.point_index,
                product_use_id=product_use_id,
                value=value,
            )
            for request_id, value in receipt.readback.values.items()
            for product_use_id in bindings[request_id]
        )
        return values, {
            "effect_id": action.effect_id,
            "status": receipt.status,
            "metadata": dict(receipt.metadata),
            "readback_metadata": dict(receipt.readback.metadata),
        }

    def finish_run_hardware(
        self,
        run_id: str,
        command: RunHardwareFinishCommand,
    ) -> RunHardwareFinalizationReceipt:
        """Finalize every run driver once and return terminal readback."""

        with self._run_lock:
            cached = self._finished_runs.get(run_id)
        if cached is not None:
            if cached.command != command:
                raise BackendConflict(
                    "run hardware was finalized with different content"
                )
            return cached.receipt
        with self._run_operation_lock(run_id):
            with self._run_lock:
                cached = self._finished_runs.get(run_id)
            if cached is not None:
                if cached.command != command:
                    raise BackendConflict(
                        "run hardware was finalized with different content"
                    )
                return cached.receipt
            self._fence_run(run_id, command.lease_id)
            runtime = self._run_runtime_state(run_id)
            if runtime is None:
                provision = self._run_provision_state(run_id)
                if (
                    provision is None
                    or provision.receipt.status != "ready"
                    or provision.receipt.instrument_ids
                ):
                    raise BackendConflict("run has no live daemon instrument drivers")
                self._discard_run_state(run_id)
                receipt = RunHardwareFinalizationReceipt(
                    operation_id=command.operation_id,
                )
                with self._run_lock:
                    self._finished_runs[run_id] = _FinishedRunHardware(
                        command=command,
                        receipt=receipt,
                    )
                return receipt
            final_state, problems = self._finalize_run_drivers(
                run_id,
                token=command.lease_id,
                runtime=runtime,
                failed=command.failed,
                operation_id=command.operation_id,
            )
            self._discard_run_state(run_id)
            receipt = RunHardwareFinalizationReceipt(
                operation_id=command.operation_id,
                final_state=tuple(final_state),
                problems=tuple(problems),
            )
            with self._run_lock:
                self._finished_runs[run_id] = _FinishedRunHardware(
                    command=command,
                    receipt=receipt,
                )
                while len(self._finished_runs) > self._finished_run_cache_limit:
                    self._finished_runs.popitem(last=False)
            return receipt

    def _finalize_run_drivers(
        self,
        run_id: str,
        *,
        token: str,
        runtime: _LiveDrivers,
        failed: bool,
        operation_id: str,
    ) -> tuple[list[InstrumentStateSnapshot], list[Problem]]:
        problems: list[Problem] = []
        action = "abort" if failed else "cleanup"
        with runtime.lock:
            for instrument_id in reversed(tuple(runtime.drivers)):
                try:
                    _run_driver_lifecycle(runtime.drivers[instrument_id], action)
                except Exception as error:
                    self._lose_run_runtime(
                        run_id,
                        runtime,
                        token=token,
                        reason=f"run_instrument_{action}_unknown",
                    )
                    raise BackendConflict(
                        f"instrument {action} failed with unknown state"
                    ) from error
            final_state: list[InstrumentStateSnapshot] = []
            for instrument_id, driver in runtime.drivers.items():
                try:
                    final_state.append(
                        _read_driver_state(driver, instrument_id=instrument_id)
                    )
                except BackendConflict as error:
                    problems.append(
                        _hardware_problem(
                            "instrument_terminal_read_failed",
                            str(error),
                            run_id=run_id,
                            operation_id=operation_id,
                            instrument_id=instrument_id,
                        )
                    )
            for instrument_id in reversed(tuple(runtime.drivers)):
                try:
                    runtime.drivers[instrument_id].close()
                except Exception as error:
                    self._lose_run_runtime(
                        run_id,
                        runtime,
                        token=token,
                        reason="run_instrument_close_unknown",
                        skip_abort=(
                            frozenset(runtime.drivers) if failed else frozenset()
                        ),
                        skip_close=frozenset({instrument_id}),
                    )
                    raise BackendConflict(
                        "instrument close failed with unknown state"
                    ) from error
        self._pop_run_runtime(run_id, expected=runtime)
        return final_state, problems

    def _run_operation_lock(self, run_id: str) -> RLock:
        with self._run_lock:
            provision = self._run_provisions.get(run_id)
            if provision is not None:
                return provision.lock
            return self._run_open_locks.setdefault(run_id, RLock())

    def _run_provision_state(self, run_id: str) -> _RunProvision | None:
        with self._run_lock:
            return self._run_provisions.get(run_id)

    def _run_is_finalizing(self, run_id: str) -> bool:
        with self._run_lock:
            return run_id in self._finalizing_runs

    def _run_runtime_state(self, run_id: str) -> _LiveDrivers | None:
        with self._run_lock:
            return self._run_runtimes.get(run_id)

    def _store_run_provision(
        self,
        run_id: str,
        provision: _RunProvision,
        *,
        runtime: _LiveDrivers | None = None,
    ) -> None:
        with self._run_lock:
            self._run_provisions[run_id] = provision
            if runtime is not None:
                self._run_runtimes[run_id] = runtime
            self._run_open_locks.pop(run_id, None)

    def _pop_run_runtime(
        self,
        run_id: str,
        *,
        expected: _LiveDrivers | None = None,
    ) -> _LiveDrivers | None:
        with self._run_lock:
            runtime = self._run_runtimes.get(run_id)
            if expected is not None and runtime is not expected:
                return None
            return self._run_runtimes.pop(run_id, None)

    def _run_driver(
        self,
        run_id: str,
        instrument_id: str,
    ) -> tuple[_LiveDrivers, InstrumentDriver]:
        runtime = self._run_runtime_state(run_id)
        if runtime is None:
            raise BackendConflict("run has no live daemon instrument drivers")
        try:
            return runtime, runtime.drivers[instrument_id]
        except KeyError as error:
            raise BackendNotFound(
                f"instrument is not live for run {run_id}: {instrument_id}"
            ) from error

    def open_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionOpenReceipt:
        with self._open_lock:
            return self._open_session(command)

    def _open_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionOpenReceipt:
        active = self._config.get_active_config()
        configured = {
            spec.id: spec for spec in active.config.instrument_registry.instruments
        }
        missing = tuple(
            instrument_id
            for instrument_id in command.instrument_ids
            if instrument_id not in configured
        )
        if missing:
            raise BackendNotFound(f"instrument was not found: {', '.join(missing)}")
        system = self._system(active.config)
        provider = self._provider(active.config)
        descriptions = self._selected_descriptions(
            provider,
            config=active.config,
            instrument_ids=command.instrument_ids,
        )
        try:
            session = self._control.open_instrument_session(
                operation_id=command.operation_id,
                actor=command.actor,
                config_entry_id=active.entry.id,
                config_content_hash=active.entry.content_hash,
                instrument_ids=command.instrument_ids,
            )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        with self._sessions_lock:
            existing_runtime = self._sessions.get(session.session_id)
        if existing_runtime is not None:
            return self._wire_session(session, existing_runtime)

        try:
            runtime, _metadata = _provide_drivers(
                provider,
                config=active.config,
                instrument_ids=command.instrument_ids,
                expected=descriptions,
                payload_codecs=system.payload_codecs,
            )
        except _ProvisioningRejected as error:
            close_failed = _call_all(error.drivers, _close_driver)
            if close_failed:
                self._mark_unknown(
                    session,
                    reason="instrument_provisioning_cleanup_failed",
                )
            else:
                self._control.close_instrument_session(
                    session.session_id,
                    status="aborted",
                )
            raise BackendConflict(str(error)) from error
        except _ProvisioningUnknown as error:
            _call_all(error.drivers, _abort_driver)
            _call_all(error.drivers, _close_driver)
            self._mark_unknown(session, reason="instrument_provisioning_unknown")
            raise BackendConflict(
                "instrument provider failed while connecting"
            ) from error

        with self._sessions_lock:
            self._sessions[session.session_id] = runtime
        return self._wire_session(session, runtime)

    def read_state(
        self,
        session_id: str,
        instrument_id: str,
    ) -> InstrumentStateSnapshot:
        runtime = self._live_runtime(session_id)
        with runtime.lock:
            _session, _runtime, driver = self._session_driver(
                session_id,
                instrument_id,
            )
            return _read_driver_state(driver, instrument_id=instrument_id)

    def apply_state(
        self,
        session_id: str,
        instrument_id: str,
        command: InstrumentStateCommand,
    ) -> ApplyReceipt:
        if command.instrument_id != instrument_id:
            raise BackendConflict("instrument apply command does not match its route")
        runtime = self._live_runtime(session_id)
        with runtime.lock:
            session, _runtime, driver = self._session_driver(
                session_id,
                instrument_id,
            )
            command_id = command.command_id
            assert command_id is not None
            return self._apply_live(
                runtime,
                driver,
                command=command,
                conflict_scope="interactive",
                on_started=lambda: self._record_operation_started(
                    session,
                    instrument_id=instrument_id,
                    operation_id=command_id,
                    kind="apply",
                ),
                on_finished=lambda status: self._record_operation_finished(
                    session,
                    instrument_id=instrument_id,
                    operation_id=command_id,
                    kind="apply",
                    status=status,
                ),
                on_unknown=lambda reason: self._lose_runtime(
                    session,
                    runtime,
                    reason=reason,
                ),
            )

    def invoke(
        self,
        session_id: str,
        instrument_id: str,
        command: InvokeCommand,
    ) -> InvokeReceipt:
        if command.instrument_id != instrument_id:
            raise BackendConflict("instrument invoke command does not match its route")
        runtime = self._live_runtime(session_id)
        with runtime.lock:
            session, _runtime, driver = self._session_driver(
                session_id,
                instrument_id,
            )
            command_id = command.command_id
            assert command_id is not None
            return self._invoke_live(
                runtime,
                driver,
                command=command,
                conflict_scope="interactive",
                on_started=lambda: self._record_operation_started(
                    session,
                    instrument_id=instrument_id,
                    operation_id=command_id,
                    kind="invoke",
                ),
                on_finished=lambda status: self._record_operation_finished(
                    session,
                    instrument_id=instrument_id,
                    operation_id=command_id,
                    kind="invoke",
                    status=status,
                ),
                on_unknown=lambda reason: self._lose_runtime(
                    session,
                    runtime,
                    reason=reason,
                ),
            )

    def collect(
        self,
        session_id: str,
        instrument_id: str,
        command: CollectCommand,
    ) -> CollectReceipt:
        if command.instrument_id != instrument_id:
            raise BackendConflict("instrument collect command does not match its route")
        if command.point_index != 0 or command.point_count != 1:
            raise BackendConflict("interactive collect uses exactly one implicit point")
        runtime = self._live_runtime(session_id)
        with runtime.lock:
            session, _runtime, driver = self._session_driver(
                session_id,
                instrument_id,
            )
            command_id = command.command_id
            assert command_id is not None
            return self._collect_live(
                runtime,
                driver,
                command=command,
                conflict_scope="interactive",
                on_started=lambda: self._record_operation_started(
                    session,
                    instrument_id=instrument_id,
                    operation_id=command_id,
                    kind="collect",
                ),
                on_finished=lambda status: self._record_operation_finished(
                    session,
                    instrument_id=instrument_id,
                    operation_id=command_id,
                    kind="collect",
                    status=status,
                ),
                on_unknown=lambda reason: self._lose_runtime(
                    session,
                    runtime,
                    reason=reason,
                ),
            )

    def _apply_live(
        self,
        runtime: _LiveDrivers,
        driver: InstrumentDriver,
        *,
        command: InstrumentStateCommand,
        conflict_scope: str,
        on_started: Callable[[], None],
        on_finished: Callable[[str], None],
        on_unknown: Callable[[str], None],
    ) -> ApplyReceipt:
        validation_problems = validate_state_command(
            command=command,
            description=runtime.descriptions[command.instrument_id],
        )
        if validation_problems:
            raise BackendConflict(
                "; ".join(item.message for item in validation_problems)
            )
        command_id = command.command_id
        assert command_id is not None
        cached = runtime.apply_receipts.get(command_id)
        if cached is not None:
            cached_command, cached_receipt = cached
            if cached_command != command:
                raise BackendConflict(
                    f"{conflict_scope} command id has different apply content"
                )
            return cached_receipt
        if (
            command_id in runtime.collect_receipts
            or command_id in runtime.collect_failures
            or command_id in runtime.invoke_receipts
        ):
            raise BackendConflict(
                f"{conflict_scope} command id was already used for another command kind"
            )
        on_started()
        try:
            receipt = driver.apply_state(command)
        except Exception as error:
            on_unknown("instrument_apply_unknown")
            raise BackendConflict(
                "instrument apply failed with unknown state"
            ) from error
        runtime.apply_receipts[command_id] = (command, receipt)
        try:
            on_finished(receipt.status)
        except Exception as error:
            on_unknown("instrument_apply_audit_unknown")
            raise BackendConflict(
                "instrument apply completed but audit recording failed"
            ) from error
        if receipt.status == "unknown":
            on_unknown("instrument_apply_receipt_unknown")
        return receipt

    def _invoke_live(
        self,
        runtime: _LiveDrivers,
        driver: InstrumentDriver,
        *,
        command: InvokeCommand,
        conflict_scope: str,
        on_started: Callable[[], None],
        on_finished: Callable[[str], None],
        on_unknown: Callable[[str], None],
    ) -> InvokeReceipt:
        validation_problems = validate_invoke_command(
            command=command,
            description=runtime.descriptions[command.instrument_id],
        )
        codec_issues = _payload_codec_issues(
            command.payloads,
            runtime.payload_codecs,
        )
        if validation_problems or codec_issues:
            raise BackendConflict(
                "; ".join(
                    [
                        *(item.message for item in validation_problems),
                        *(message for _code, message in codec_issues),
                    ]
                )
            )
        canonical_command = self._payloads.canonicalize_invoke_command(command)
        command_id = canonical_command.command_id
        assert command_id is not None
        cached = runtime.invoke_receipts.get(command_id)
        if cached is not None:
            cached_command, cached_receipt = cached
            if cached_command != canonical_command:
                raise BackendConflict(
                    f"{conflict_scope} command id has different invoke content"
                )
            return cached_receipt
        if (
            command_id in runtime.apply_receipts
            or command_id in runtime.collect_receipts
            or command_id in runtime.collect_failures
        ):
            raise BackendConflict(
                f"{conflict_scope} command id was already used for another command kind"
            )
        driver_command = self._payloads.materialize_invoke_command(canonical_command)
        on_started()
        try:
            receipt = driver.invoke(driver_command)
        except Exception as error:
            on_unknown("instrument_invoke_unknown")
            raise BackendConflict(
                "instrument invoke failed with unknown state"
            ) from error
        if receipt.status == "invoked":
            try:
                next_state = receipt.state or _read_driver_state(
                    driver,
                    instrument_id=command.instrument_id,
                )
            except Exception as error:
                on_unknown("instrument_invoke_state_unknown")
                raise BackendConflict(
                    "instrument invoke completed but state synchronization failed"
                ) from error
            if next_state.instrument_id != command.instrument_id:
                on_unknown("instrument_invoke_state_mismatch")
                raise BackendConflict(
                    "instrument invoke returned state for another device"
                )
            runtime.assumed_states[command.instrument_id] = next_state.model_copy(
                deep=True
            )
            receipt = receipt.model_copy(update={"state": next_state})
        runtime.invoke_receipts[command_id] = (canonical_command, receipt)
        try:
            on_finished(receipt.status)
        except Exception as error:
            on_unknown("instrument_invoke_audit_unknown")
            raise BackendConflict(
                "instrument invoke completed but audit recording failed"
            ) from error
        if receipt.status == "unknown":
            on_unknown("instrument_invoke_receipt_unknown")
        return receipt

    def _collect_live(
        self,
        runtime: _LiveDrivers,
        driver: InstrumentDriver,
        *,
        command: CollectCommand,
        conflict_scope: str,
        on_started: Callable[[], None],
        on_finished: Callable[[str], None],
        on_unknown: Callable[[str], None],
    ) -> CollectReceipt:
        validation_problems = validate_collect_command(
            command=command,
            description=runtime.descriptions[command.instrument_id],
        )
        if validation_problems:
            raise BackendConflict(
                "; ".join(item.message for item in validation_problems)
            )
        command_id = command.command_id
        assert command_id is not None
        cached = runtime.collect_receipts.get(command_id)
        if cached is not None:
            cached_command, cached_receipt = cached
            if cached_command != command:
                raise BackendConflict(
                    f"{conflict_scope} command id has different collect content"
                )
            return cached_receipt
        cached_failure = runtime.collect_failures.get(command_id)
        if cached_failure is not None:
            cached_command, cached_message = cached_failure
            if cached_command != command:
                raise BackendConflict(
                    f"{conflict_scope} command id has different collect content"
                )
            raise BackendConflict(cached_message)
        if (
            command_id in runtime.apply_receipts
            or command_id in runtime.invoke_receipts
        ):
            raise BackendConflict(
                f"{conflict_scope} command id was already used for another command kind"
            )
        on_started()
        try:
            receipt = driver.collect(command)
        except Exception as error:
            on_unknown("instrument_collect_unknown")
            raise BackendConflict(
                "instrument collect failed with unknown state"
            ) from error
        receipt_problems = validate_collect_receipt(
            command=command,
            receipt=receipt,
        )
        if receipt_problems:
            message = "; ".join(item.message for item in receipt_problems)
            try:
                on_finished("invalid_receipt")
            except Exception as error:
                on_unknown("instrument_collect_audit_unknown")
                raise BackendConflict(
                    "instrument collect completed but audit recording failed"
                ) from error
            runtime.collect_failures[command_id] = (command, message)
            raise BackendConflict(message)
        runtime.collect_receipts[command_id] = (command, receipt)
        try:
            on_finished(receipt.status)
        except Exception as error:
            on_unknown("instrument_collect_audit_unknown")
            raise BackendConflict(
                "instrument collect completed but audit recording failed"
            ) from error
        if receipt.status == "unknown":
            on_unknown("instrument_collect_receipt_unknown")
        return receipt

    def close_session(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return self._end_session(
            session_id,
            abort=False,
        )

    def abort_session(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return self._end_session(
            session_id,
            abort=True,
        )

    def resolve_attention(self, session_id: str) -> InstrumentSessionEndReceipt:
        with self._open_lock, self._attention_lock:
            try:
                session = self._control.get_instrument_session(session_id)
                if session.state == "attention_required":
                    self._cleanup_session_runtime(session_id)
                self._control.resolve_instrument_session_attention(session_id)
            except ControlPlaneNotFound as error:
                raise BackendNotFound(str(error)) from error
            except ControlPlaneConflict as error:
                raise BackendConflict(str(error)) from error
        return InstrumentSessionEndReceipt(
            session_id=session_id,
            status="aborted",
        )

    def _cleanup_session_runtime(self, session_id: str) -> None:
        with self._sessions_lock:
            runtime = self._sessions.get(session_id)
        if runtime is None:
            return
        with runtime.lock:
            with self._sessions_lock:
                if self._sessions.get(session_id) is not runtime:
                    return
            _call_all(runtime.drivers.values(), _abort_driver)
            _call_all(runtime.drivers.values(), _close_driver)
            with self._sessions_lock:
                if self._sessions.get(session_id) is runtime:
                    self._sessions.pop(session_id)

    def expire_leases(self) -> None:
        """Fence expired executors and finish their daemon-owned cleanup."""

        with self._attention_lock:
            self.expire_runs(self._control.expire_executor_leases())

    def finalize_run(self, run_id: str, *, token: str) -> None:
        """Release any drivers left behind before committing a terminal run."""

        with self._run_operation_lock(run_id):
            self._fence_run(run_id, token)
            with self._run_lock:
                self._finalizing_runs.add(run_id)
            runtime = self._run_runtime_state(run_id)
            if runtime is None:
                return
            self._finalize_run_drivers(
                run_id,
                token=token,
                runtime=runtime,
                failed=True,
                operation_id="hardware.terminal-fallback",
            )

    def release_run(self, run_id: str) -> None:
        """Drop volatile idempotency state after the run is durably closed."""

        self._discard_run_state(run_id)

    def _discard_run_state(self, run_id: str) -> None:
        with self._run_lock:
            self._run_runtimes.pop(run_id, None)
            self._run_provisions.pop(run_id, None)
            self._run_open_locks.pop(run_id, None)
            self._finalizing_runs.discard(run_id)

    def expire_runs(self, run_ids: Iterable[str]) -> None:
        """Release in-memory drivers after their executor leases were fenced."""

        for run_id in run_ids:
            self._cleanup_run_state(run_id)

    def await_run_cleanup(self, run_id: str) -> None:
        """Complete hardware cleanup before quarantined resources are released."""

        try:
            run = self._control.get_run(run_id)
        except ControlPlaneNotFound:
            return
        if run.state == "attention_required":
            self._cleanup_run_state(run_id)

    def resolve_run_attention[T](
        self,
        run_id: str,
        resolver: Callable[[str], T],
    ) -> T:
        with self._attention_lock:
            self.await_run_cleanup(run_id)
            return resolver(run_id)

    def _cleanup_run_state(self, run_id: str) -> None:
        lock = self._run_operation_lock(run_id)
        with lock:
            with self._run_lock:
                self._run_open_locks[run_id] = lock
                runtime = self._run_runtimes.pop(run_id, None)
                self._run_provisions.pop(run_id, None)
                self._finalizing_runs.discard(run_id)
            if runtime is not None:
                with runtime.lock:
                    _call_all(runtime.drivers.values(), _abort_driver)
                    _call_all(runtime.drivers.values(), _close_driver)
            with self._run_lock:
                if self._run_open_locks.get(run_id) is lock:
                    self._run_open_locks.pop(run_id)

    def reconcile_startup(self) -> None:
        with self._attention_lock:
            self.expire_runs(self._control.abandon_executor_leases())
            self._control.reconcile_instrument_sessions_after_restart()

    def shutdown(self) -> None:
        with self._sessions_lock:
            sessions = tuple(self._sessions.items())
            self._sessions.clear()
        for session_id, runtime in sessions:
            try:
                session = self._control.get_instrument_session(session_id)
            except ControlPlaneNotFound:
                session = None
            with runtime.lock:
                failed = _call_all(runtime.drivers.values(), _abort_driver)
                failed = _call_all(runtime.drivers.values(), _close_driver) or failed
            if session is not None and session.state == "active":
                if failed:
                    self._mark_unknown(
                        session,
                        reason="instrument_shutdown_cleanup_unknown",
                    )
                else:
                    self._control.close_instrument_session(
                        session_id,
                        status="aborted",
                    )
        with self._run_lock:
            run_provisions = tuple(self._run_provisions.items())
            run_runtimes = self._run_runtimes
            self._run_provisions = {}
            self._run_runtimes = {}
            self._run_open_locks = {}
            self._finalizing_runs = set()
        for run_id, provision in run_provisions:
            runtime = run_runtimes.get(run_id)
            if runtime is not None:
                with runtime.lock:
                    _call_all(runtime.drivers.values(), _abort_driver)
                    _call_all(runtime.drivers.values(), _close_driver)
            self._mark_run_unknown(
                run_id,
                token=provision.command.lease_id,
                reason="daemon_shutting_down",
            )
        with self._provider_lock:
            self._system_content_hash = None
            self._cached_system = None

    def _end_session(
        self,
        session_id: str,
        *,
        abort: bool,
    ) -> InstrumentSessionEndReceipt:
        try:
            session = self._control.get_instrument_session(session_id)
            if session.state == "closed":
                assert session.end_status is not None
                return InstrumentSessionEndReceipt(
                    session_id=session_id,
                    status=session.end_status,
                )
            session = self._control.validate_instrument_session(session_id)
            runtime = self._live_runtime(session_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        with runtime.lock:
            try:
                session = self._control.validate_instrument_session(session_id)
            except ControlPlaneConflict as error:
                raise BackendConflict(str(error)) from error
            failed = (
                _call_all(runtime.drivers.values(), _abort_driver) if abort else False
            )
            failed = _call_all(runtime.drivers.values(), _close_driver) or failed
            if failed:
                self._lose_runtime(
                    session,
                    runtime,
                    reason=(
                        "instrument_abort_unknown"
                        if abort
                        else "instrument_close_unknown"
                    ),
                )
                raise BackendConflict("instrument connection release was not confirmed")
            try:
                self._control.close_instrument_session(
                    session_id,
                    status="aborted" if abort else "closed",
                )
            except ControlPlaneConflict as error:
                raise BackendConflict(str(error)) from error
            with self._sessions_lock:
                self._sessions.pop(session_id, None)
            return InstrumentSessionEndReceipt(
                session_id=session_id,
                status="aborted" if abort else "closed",
            )

    def _session_driver(
        self,
        session_id: str,
        instrument_id: str,
    ) -> tuple[InstrumentSession, _LiveDrivers, InstrumentDriver]:
        try:
            session = self._control.validate_instrument_session(session_id)
            runtime = self._live_runtime(session_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        try:
            driver = runtime.drivers[instrument_id]
        except KeyError as error:
            raise BackendNotFound(
                f"instrument is not in session {session_id}: {instrument_id}"
            ) from error
        return session, runtime, driver

    def _live_runtime(self, session_id: str) -> _LiveDrivers:
        with self._sessions_lock:
            runtime = self._sessions.get(session_id)
        if runtime is None:
            raise BackendConflict("instrument session has no live daemon drivers")
        return runtime

    def _pop_runtime(self, session_id: str) -> _LiveDrivers | None:
        with self._sessions_lock:
            return self._sessions.pop(session_id, None)

    def _lose_runtime(
        self,
        session: InstrumentSession,
        runtime: _LiveDrivers,
        *,
        reason: str,
    ) -> None:
        _call_all(runtime.drivers.values(), _abort_driver)
        _call_all(runtime.drivers.values(), _close_driver)
        self._pop_runtime(session.session_id)
        self._mark_unknown(session, reason=reason)

    def _lose_run_runtime(
        self,
        run_id: str,
        runtime: _LiveDrivers,
        *,
        token: str,
        reason: str,
        skip_abort: frozenset[str] | None = None,
        skip_close: frozenset[str] | None = None,
    ) -> None:
        drivers = tuple(runtime.drivers.values())
        skipped_aborts = skip_abort or frozenset()
        skipped_closes = skip_close or frozenset()
        _call_all(
            (
                driver
                for driver in drivers
                if driver.instrument_id not in skipped_aborts
            ),
            _abort_driver,
        )
        _call_all(
            (
                driver
                for driver in drivers
                if driver.instrument_id not in skipped_closes
            ),
            _close_driver,
        )
        self._pop_run_runtime(run_id, expected=runtime)
        self._mark_run_unknown(
            run_id,
            token=token,
            reason=reason,
        )

    def _mark_unknown(
        self,
        session: InstrumentSession,
        *,
        reason: str,
    ) -> None:
        with suppress(InstrumentSessionNotActive):
            self._control.mark_instrument_session_unknown(
                session.session_id,
                reason=reason,
            )

    def _record_operation_started(
        self,
        session: InstrumentSession,
        *,
        instrument_id: str,
        operation_id: str,
        kind: Literal["apply", "invoke", "collect"],
    ) -> None:
        try:
            self._control.start_instrument_operation(
                session.session_id,
                instrument_id=instrument_id,
                operation_id=operation_id,
                kind=kind,
            )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error

    def _record_operation_finished(
        self,
        session: InstrumentSession,
        *,
        instrument_id: str,
        operation_id: str,
        kind: Literal["apply", "invoke", "collect"],
        status: str,
    ) -> None:
        try:
            self._control.finish_instrument_operation(
                session.session_id,
                instrument_id=instrument_id,
                operation_id=operation_id,
                kind=kind,
                status=status,
            )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error

    def _fence_run(self, run_id: str, token: str) -> None:
        try:
            self._control.validate_executor_lease(run_id, token=token)
        except ExecutorLeaseNotHeld as error:
            raise BackendConflict(
                "executor lease is absent, stale, or expired"
            ) from error

    def _mark_run_unknown(
        self,
        run_id: str,
        *,
        token: str,
        reason: str,
    ) -> None:
        try:
            with suppress(ExecutorLeaseNotHeld):
                self._control.mark_executor_unknown(
                    run_id,
                    token=token,
                    reason=reason,
                )
        finally:
            self._discard_run_state(run_id)

    def _record_run_operation_event(
        self,
        run_id: str,
        *,
        token: str,
        instrument_id: str | None,
        operation_id: str,
        event_kind: str,
        status: str | None,
        details: Mapping[str, JsonValue] | None = None,
    ) -> None:
        payload: dict[str, JsonValue] = {"operation_id": operation_id}
        if instrument_id is not None:
            payload["instrument_id"] = instrument_id
        if status is not None:
            payload["status"] = status
        payload.update(details or {})
        try:
            with self._control.fenced_transaction(
                run_id,
                token=token,
            ) as connection:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind=event_kind,
                        payload=payload,
                    ),
                )
        except (ControlPlaneConflict, ExecutorLeaseNotHeld) as error:
            raise BackendConflict(
                "executor lease is absent, stale, or expired"
            ) from error
        except Exception as error:
            raise BackendConflict(
                "run instrument audit event could not be recorded"
            ) from error

    def _descriptions(
        self,
        config: ConfigProfileSnapshot,
    ) -> tuple[dict[str, InstrumentDescription], tuple[Problem, ...]]:
        if self._build_system is None:
            return {}, ()
        try:
            provider = self._provider(config)
            result = provider.describe(InstrumentProviderContext(config=config))
        except Exception:
            return {}, ()
        return (
            {
                description.instrument_id: description
                for description in result.instruments
            },
            result.problems,
        )

    def _selected_descriptions(
        self,
        provider: InstrumentProvider,
        *,
        config: ConfigProfileSnapshot,
        instrument_ids: tuple[str, ...],
    ) -> dict[str, InstrumentDescription]:
        try:
            result = provider.describe(
                InstrumentProviderContext(
                    config=config,
                    instrument_ids=instrument_ids,
                )
            )
        except Exception as error:
            raise BackendConflict("instrument provider description failed") from error
        if result.problems:
            raise BackendConflict("instrument provider cannot describe the session")
        descriptions = {
            description.instrument_id: description
            for description in result.instruments
            if description.instrument_id in instrument_ids
        }
        missing = tuple(
            instrument_id
            for instrument_id in instrument_ids
            if instrument_id not in descriptions
        )
        if missing:
            raise BackendConflict(
                f"instrument provider does not expose: {', '.join(missing)}"
            )
        return descriptions

    def _provider(self, config: ConfigProfileSnapshot) -> InstrumentProvider:
        system = self._system(config)
        if system.provider is None:
            raise BackendConflict(
                "project experiment system does not configure an instrument provider"
            )
        return system.provider

    def _system(self, config: ConfigProfileSnapshot) -> ExperimentSystem:
        if self._build_system is None:
            raise BackendConflict(
                "project application does not configure an instrument provider"
            )
        content_hash = config_content_hash(config)
        with self._provider_lock:
            if (
                self._system_content_hash == content_hash
                and self._cached_system is not None
            ):
                return self._cached_system
            system = self._build_system(config)
            self._system_content_hash = content_hash
            self._cached_system = system
            return system

    def _wire_session(
        self,
        session: InstrumentSession,
        runtime: _LiveDrivers,
    ) -> InstrumentSessionOpenReceipt:
        return InstrumentSessionOpenReceipt(
            session_id=session.session_id,
            actor=session.actor,
            config_entry_id=session.config_entry_id,
            config_content_hash=session.config_content_hash,
            instrument_ids=session.instrument_ids,
            descriptions=tuple(
                runtime.descriptions[instrument_id]
                for instrument_id in session.instrument_ids
            ),
            opened_at=session.acquired_at,
        )

    @staticmethod
    def _instrument_view(
        spec: InstrumentSpec,
        *,
        description: InstrumentDescription | None,
        claim: ResourceClaim | None,
        owner_actor: str | None,
        problems: tuple[Problem, ...],
    ) -> InstrumentView:
        if claim is not None:
            availability = claim.status
        elif description is None:
            availability = "unavailable"
        else:
            availability = "available"
        return InstrumentView(
            spec=spec,
            description=description,
            availability=availability,
            owner_kind=None if claim is None else claim.owner_kind,
            owner_id=None if claim is None else claim.owner_id,
            owner_actor=owner_actor,
            problems=problems,
        )


class _ProvisioningRejected(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        problems: tuple[Problem, ...],
        drivers: tuple[InstrumentDriver, ...],
    ) -> None:
        self.problems = problems
        self.drivers = drivers
        super().__init__(message)


class _ProvisioningUnknown(RuntimeError):
    def __init__(self, drivers: tuple[InstrumentDriver, ...]) -> None:
        self.drivers = drivers
        super().__init__("instrument provisioning state is unknown")


def _provide_drivers(
    provider: InstrumentProvider,
    *,
    config: ConfigProfileSnapshot,
    instrument_ids: tuple[str, ...],
    expected: Mapping[str, InstrumentDescription],
    payload_codecs: PayloadCodecRegistry,
) -> tuple[_LiveDrivers, dict[str, JsonValue]]:
    drivers: tuple[InstrumentDriver, ...] = ()
    try:
        result = provider.provide(
            InstrumentProviderContext(
                config=config,
                instrument_ids=instrument_ids,
            )
        )
        drivers = result.drivers
        if result.problems:
            raise _ProvisioningRejected(
                "instrument provider rejected provisioning",
                problems=result.problems,
                drivers=drivers,
            )
        problems = validate_instruments(
            config=config,
            instruments=list(drivers),
        )
        actual, description_problems = describe_instruments(list(drivers))
        problems.extend(description_problems)
        actual_by_id = {
            description.instrument_id: description for description in actual
        }
        if tuple(actual_by_id) != instrument_ids:
            problems.append(
                _provision_problem(
                    "instrument_provider_result_order_mismatch",
                    "instrument provider did not return requested drivers in order",
                )
            )
        for instrument_id in set(instrument_ids) & actual_by_id.keys():
            if actual_by_id[instrument_id] != expected[instrument_id]:
                problems.append(
                    _provision_problem(
                        "instrument_description_changed",
                        (
                            f"instrument description changed while provisioning "
                            f"{instrument_id}"
                        ),
                        instrument_id=instrument_id,
                    )
                )
        if problems:
            raise _ProvisioningRejected(
                "instrument provider returned invalid drivers",
                problems=tuple(problems),
                drivers=drivers,
            )
        return (
            _LiveDrivers(
                drivers={driver.instrument_id: driver for driver in drivers},
                descriptions=actual_by_id,
                payload_codecs=payload_codecs,
            ),
            result.metadata,
        )
    except _ProvisioningRejected:
        raise
    except Exception as error:
        raise _ProvisioningUnknown(drivers) from error


def _provision_problem(
    code: str,
    message: str,
    *,
    run_id: str | None = None,
    operation_id: str | None = None,
    instrument_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> Problem:
    location = (
        RuntimeLocation(
            run_id=run_id,
            operation_id=operation_id,
            instrument_id=instrument_id,
        )
        if run_id is not None or operation_id is not None
        else ModelLocation(
            root="instrument_provider",
            path=(() if instrument_id is None else ("instruments", instrument_id)),
        )
    )
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=location,
        details=details,
    )


def _hardware_problem(
    code: str,
    message: str,
    *,
    run_id: str,
    operation_id: str,
    instrument_id: str | None = None,
    point_index: int | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=RuntimeLocation(
            run_id=run_id,
            operation_id=operation_id,
            instrument_id=instrument_id,
            point_index=point_index,
        ),
    )


def _payload_codec_issues(
    payloads: Mapping[str, CommandPayload],
    registry: PayloadCodecRegistry,
) -> tuple[tuple[str, str], ...]:
    issues: list[tuple[str, str]] = []
    for payload_id, payload in payloads.items():
        try:
            registry.validate_descriptor(payload)
        except LookupError as error:
            issues.append(
                (
                    "instrument_payload_codec_unavailable",
                    f"payload {payload_id!r}: {error}",
                )
            )
        except ValueError as error:
            issues.append(
                (
                    "instrument_payload_codec_mismatch",
                    f"payload {payload_id!r}: {error}",
                )
            )
    return tuple(issues)


def _payload_codec_problems(
    payloads: Mapping[str, CommandPayload],
    registry: PayloadCodecRegistry,
    *,
    run_id: str,
    operation_id: str,
    instrument_id: str,
    point_index: int,
) -> tuple[Problem, ...]:
    return tuple(
        _hardware_problem(
            code,
            message,
            run_id=run_id,
            operation_id=operation_id,
            instrument_id=instrument_id,
            point_index=point_index,
        )
        for code, message in _payload_codec_issues(payloads, registry)
    )


def _state_value(
    current: InstrumentStateSnapshot,
    target: InstrumentStateAssignment,
) -> object:
    identity = property_target_identity(
        target.interface_id,
        target.component_path,
        target.property_id,
        target.entity_ids,
        target.channel_bindings,
    )
    return next(
        (
            item.value
            for item in current.properties
            if property_target_identity(
                item.interface_id,
                item.component_path,
                item.property_id,
                item.entity_ids,
                item.channel_bindings,
            )
            == identity
        ),
        None,
    )


def _call_all(
    drivers: Iterable[InstrumentDriver],
    operation: Callable[[InstrumentDriver], None],
) -> bool:
    failed = False
    for driver in reversed(tuple(drivers)):
        try:
            operation(driver)
        except Exception:
            failed = True
    return failed


def _close_driver(driver: InstrumentDriver) -> None:
    driver.close()


def _abort_driver(driver: InstrumentDriver) -> None:
    driver.abort()


def _read_driver_state(
    driver: InstrumentDriver,
    *,
    instrument_id: str,
) -> InstrumentStateSnapshot:
    try:
        state = driver.read_state()
    except Exception as error:
        raise BackendConflict("instrument state read failed") from error
    if state.instrument_id != instrument_id:
        raise BackendConflict("instrument returned state for another instrument")
    return state


def _run_driver_lifecycle(
    driver: InstrumentDriver,
    action: Literal["cleanup", "abort", "close"],
) -> None:
    if action == "cleanup":
        driver.cleanup()
    elif action == "abort":
        driver.abort()
    else:
        driver.close()


def _scope_provider_problems(
    specs: list[InstrumentSpec],
    problems: tuple[Problem, ...],
) -> tuple[tuple[Problem, ...], dict[str, tuple[Problem, ...]]]:
    instrument_ids = {spec.id for spec in specs}
    scoped: dict[str, list[Problem]] = {}
    global_problems: list[Problem] = []
    for item in problems:
        owners = _problem_instrument_ids(
            item,
            specs=specs,
            instrument_ids=instrument_ids,
        )
        if not owners:
            global_problems.append(item)
            continue
        for instrument_id in owners:
            scoped.setdefault(instrument_id, []).append(item)
    return (
        tuple(global_problems),
        {instrument_id: tuple(items) for instrument_id, items in scoped.items()},
    )


def _problem_instrument_ids(
    problem: Problem,
    *,
    specs: list[InstrumentSpec],
    instrument_ids: set[str],
) -> tuple[str, ...]:
    selected: set[str] = set()
    detail_id = problem.details.get("instrument_id")
    if isinstance(detail_id, str) and detail_id in instrument_ids:
        selected.add(detail_id)
    for location in (
        *((problem.location,) if problem.location is not None else ()),
        *problem.related_locations,
    ):
        if (
            isinstance(location, RuntimeLocation)
            and location.instrument_id in instrument_ids
        ):
            assert location.instrument_id is not None
            selected.add(location.instrument_id)
        elif isinstance(location, ModelLocation):
            selected.update(
                item
                for item in location.path
                if isinstance(item, str) and item in instrument_ids
            )
            for index, item in enumerate(location.path[:-1]):
                candidate = location.path[index + 1]
                if (
                    item == "instruments"
                    and isinstance(candidate, int)
                    and candidate < len(specs)
                ):
                    selected.add(specs[candidate].id)
    return tuple(sorted(selected))


__all__ = ["InstrumentService"]
