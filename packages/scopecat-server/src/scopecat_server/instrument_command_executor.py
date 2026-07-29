"""Execute one validated driver command and synchronize its physical state."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from scopecat.kernel.problems import Problem
from scopecat.kernel.value_identity import scalar_identity
from scopecat.records.instrument import (
    InstrumentStateSnapshot,
    property_target_identity,
)
from scopecat.sdk.instruments.backend import (
    BackendApplyRequest,
    BackendCollectRequest,
    BackendInvokeRequest,
)
from scopecat.sdk.instruments.commands import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentStateAssignment,
    InvokeReceipt,
)
from scopecat.sdk.instruments.contracts import (
    validate_collect_receipt,
    validate_state_snapshot,
)

from .errors import BackendConflict
from .instrument_actor import OwnedInstrument

type InstrumentCommandFailureReason = Literal[
    "instrument_apply_unknown",
    "instrument_apply_state_unknown",
    "instrument_invoke_unknown",
    "instrument_invoke_state_unknown",
    "instrument_invoke_state_mismatch",
    "instrument_collect_unknown",
    "instrument_collect_receipt_invalid",
    "instrument_collect_rejection_state_unknown",
]


class InstrumentCommandExecutionError(RuntimeError):
    def __init__(
        self,
        reason: InstrumentCommandFailureReason,
        message: str,
        *,
        problems: Sequence[Problem] = (),
    ) -> None:
        self.reason = reason
        self.problems = tuple(problems)
        super().__init__(message)


def execute_instrument_apply(
    instrument: OwnedInstrument,
    request: BackendApplyRequest,
    *,
    assignments: Sequence[InstrumentStateAssignment],
) -> ApplyReceipt:
    try:
        receipt = instrument.apply_state(request)
    except Exception as error:
        raise InstrumentCommandExecutionError(
            "instrument_apply_unknown",
            "instrument apply failed with unknown state",
        ) from error
    if receipt.status != "applied":
        return receipt
    try:
        state = _confirmed_applied_state(instrument, receipt, assignments)
    except BackendConflict as error:
        raise InstrumentCommandExecutionError(
            "instrument_apply_state_unknown",
            f"instrument apply completed but {error}",
        ) from error
    instrument.adopt_state(state)
    return receipt.model_copy(update={"state": state})


def execute_instrument_invoke(
    instrument: OwnedInstrument,
    request: BackendInvokeRequest,
) -> InvokeReceipt:
    try:
        receipt = instrument.invoke(request)
    except Exception as error:
        raise InstrumentCommandExecutionError(
            "instrument_invoke_unknown",
            "instrument invoke failed with unknown state",
        ) from error
    if receipt.status != "invoked":
        return receipt
    if receipt.state is None:
        try:
            state = observe_instrument(instrument)
        except BackendConflict as error:
            raise InstrumentCommandExecutionError(
                "instrument_invoke_state_unknown",
                "instrument invoke completed but state synchronization failed",
            ) from error
    else:
        state = receipt.state
        problems = validate_state_snapshot(
            snapshot=state,
            description=instrument.description,
        )
        if problems:
            raise InstrumentCommandExecutionError(
                "instrument_invoke_state_mismatch",
                "; ".join(item.message for item in problems),
                problems=problems,
            )
    instrument.adopt_state(state)
    return receipt.model_copy(update={"state": state})


def execute_instrument_collect(
    instrument: OwnedInstrument,
    request: BackendCollectRequest,
    *,
    command: CollectCommand,
) -> CollectReceipt:
    try:
        receipt = instrument.collect(request)
    except Exception as error:
        raise InstrumentCommandExecutionError(
            "instrument_collect_unknown",
            "instrument collect failed with unknown state",
        ) from error
    problems = validate_collect_receipt(
        command=command,
        receipt=receipt,
    )
    if problems:
        raise InstrumentCommandExecutionError(
            "instrument_collect_receipt_invalid",
            "; ".join(item.message for item in problems),
            problems=problems,
        )
    if receipt.status == "not_collected":
        try:
            instrument.adopt_state(observe_instrument(instrument))
        except BackendConflict as error:
            raise InstrumentCommandExecutionError(
                "instrument_collect_rejection_state_unknown",
                "instrument rejected collection and state synchronization failed",
            ) from error
    return receipt


def observe_instrument(
    instrument: OwnedInstrument,
) -> InstrumentStateSnapshot:
    try:
        state = instrument.read_state()
    except Exception as error:
        raise BackendConflict("instrument state read failed") from error
    problems = validate_state_snapshot(
        snapshot=state,
        description=instrument.description,
    )
    if problems:
        raise BackendConflict("; ".join(item.message for item in problems))
    return state


def _confirmed_applied_state(
    instrument: OwnedInstrument,
    receipt: ApplyReceipt,
    assignments: Sequence[InstrumentStateAssignment],
) -> InstrumentStateSnapshot:
    state = receipt.state
    if state is None:
        state = observe_instrument(instrument)
    else:
        problems = validate_state_snapshot(
            snapshot=state,
            description=instrument.description,
        )
        if problems:
            raise BackendConflict("; ".join(item.message for item in problems))
    if not all(
        state_assignment_satisfied(state, assignment) for assignment in assignments
    ):
        raise BackendConflict("instrument apply readback did not match requested state")
    return state


def state_assignment_satisfied(
    state: InstrumentStateSnapshot,
    assignment: InstrumentStateAssignment,
) -> bool:
    identity = property_target_identity(
        assignment.interface_id,
        assignment.component_path,
        assignment.property_id,
    )
    actual = next(
        (
            item.value
            for item in state.properties
            if property_target_identity(
                item.interface_id,
                item.component_path,
                item.property_id,
            )
            == identity
        ),
        None,
    )
    return actual is not None and (
        scalar_identity(actual.root) == scalar_identity(assignment.value.root)
    )
