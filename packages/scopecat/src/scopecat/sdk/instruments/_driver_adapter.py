"""Translate between backend requests and driver-facing values."""

from __future__ import annotations

from typing import cast

from scopecat.kernel.state import StateValue
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments.authoring import (
    DriverAcquisition,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverScalar,
    DriverState,
    DriverStateEntry,
    DriverStatePatch,
    DriverSuccess,
)
from scopecat.sdk.instruments.backend import (
    BackendApplyRequest,
    BackendCollectRequest,
)
from scopecat.sdk.instruments.commands import (
    ApplyReceipt,
    CollectReceipt,
    InvokeReceipt,
)


def project_state(
    instrument_id: str,
    state: DriverState,
) -> InstrumentStateSnapshot:
    return InstrumentStateSnapshot(
        instrument_id=instrument_id,
        properties=[
            InstrumentPropertyState(
                interface_id=target.interface_id,
                component_path=list(target.component_path),
                property_id=target.property_id,
                value=StateValue(value),
                entity_ids=list(entry.entity_ids),
                channel_bindings=list(entry.channel_bindings),
            )
            for entry in sorted(
                state.entries,
                key=lambda item: (
                    item.target.interface_id,
                    item.target.component_path,
                    item.target.property_id,
                    item.entity_ids,
                    tuple(binding.channel_id for binding in item.channel_bindings),
                ),
            )
            for target, value in ((entry.target, entry.value),)
        ],
        metadata=state.metadata,
    )


def lower_state_patch(request: BackendApplyRequest) -> DriverStatePatch:
    return DriverStatePatch(
        values={
            assignment.target: cast("DriverScalar", assignment.value.root)
            for assignment in request.assignments
            if not assignment.channel_bindings
        },
        scoped_values=tuple(
            DriverStateEntry(
                target=assignment.target,
                value=cast("DriverScalar", assignment.value.root),
                entity_ids=assignment.entity_ids,
                channel_bindings=assignment.channel_bindings,
            )
            for assignment in request.assignments
            if assignment.channel_bindings
        ),
    )


def project_apply_outcome(
    instrument_id: str,
    outcome: DriverOutcome[DriverState | None],
) -> ApplyReceipt:
    if isinstance(outcome, DriverSuccess):
        return ApplyReceipt(
            state=(
                project_state(instrument_id, outcome.value)
                if outcome.value is not None
                else None
            ),
            metadata=outcome.metadata,
        )
    if isinstance(outcome, DriverRejected):
        return ApplyReceipt(
            status="not_applied",
            problems=outcome.problems,
            metadata=outcome.metadata,
        )
    return ApplyReceipt(
        status="unknown",
        problems=outcome.problems,
        metadata=outcome.metadata,
    )


def project_invoke_outcome(
    instrument_id: str,
    outcome: DriverOutcome[DriverState | None],
) -> InvokeReceipt:
    if isinstance(outcome, DriverSuccess):
        return InvokeReceipt(
            state=(
                project_state(instrument_id, outcome.value)
                if outcome.value is not None
                else None
            ),
            metadata=outcome.metadata,
        )
    if isinstance(outcome, DriverRejected):
        return InvokeReceipt(
            status="not_invoked",
            problems=outcome.problems,
            metadata=outcome.metadata,
        )
    return InvokeReceipt(
        status="unknown",
        problems=outcome.problems,
        metadata=outcome.metadata,
    )


def lower_acquisition(request: BackendCollectRequest) -> DriverAcquisition:
    return DriverAcquisition(
        target=request.target,
        results=frozenset(request.result_target(result) for result in request.results),
        entity_ids=request.entity_ids,
        channel_bindings=request.channel_bindings,
    )


def project_collect_outcome(
    request: BackendCollectRequest,
    outcome: DriverOutcome[DriverReadback],
) -> CollectReceipt:
    if isinstance(outcome, DriverSuccess):
        requested_targets = {
            request.result_target(result) for result in request.results
        }
        values = {
            result.request_id: outcome.value.values[request.result_target(result)]
            for result in request.results
            if request.result_target(result) in outcome.value.values
        }
        # Keep extras visible to the existing receipt contract validator.
        for index, target in enumerate(
            sorted(set(outcome.value.values) - requested_targets, key=repr)
        ):
            request_id = f"driver-unrequested-{index}"
            while request_id in values:
                request_id = f"_{request_id}"
            values[request_id] = outcome.value.values[target]
        return CollectReceipt(
            readback=InstrumentReadback(
                values=values,
                metadata=outcome.value.metadata,
            ),
            metadata=outcome.metadata,
        )
    if isinstance(outcome, DriverRejected):
        return CollectReceipt(
            status="not_collected",
            problems=outcome.problems,
            metadata=outcome.metadata,
        )
    return CollectReceipt(
        status="unknown",
        problems=outcome.problems,
        metadata=outcome.metadata,
    )


__all__ = [
    "lower_acquisition",
    "lower_state_patch",
    "project_apply_outcome",
    "project_collect_outcome",
    "project_invoke_outcome",
    "project_state",
]
