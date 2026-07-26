"""Instrument state-write effects and predicted-state reconciliation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from scopecat.execution.effects.compute import PointEffectState
from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.local.program import ApplyStateOperation
from scopecat.execution.local.receipts import (
    apply_receipt_evidence,
    command_evidence,
)
from scopecat.kernel.state import PayloadRef
from scopecat.records.artifact import CommandPayload
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import (
    CommandChannelBinding,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    InstrumentDriver,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    apply_state_command_to_snapshot,
)


class StateEffectExecutor:
    """Apply state commands while retaining the last accepted instrument state."""

    def __init__(
        self,
        *,
        drivers: Mapping[str, InstrumentDriver],
        journal: JournaledEffectBoundary,
    ) -> None:
        self.drivers = drivers
        self.journal = journal
        self.current_states: dict[str, InstrumentStateSnapshot] = {}

    def execute(
        self,
        frame: PointEffectState,
        operation: ApplyStateOperation,
    ) -> bool:
        current = self.current_states.get(operation.instrument_id)
        if current is None:
            self.journal.problems.append(
                self.journal.problem(
                    "missing_current_state",
                    f"missing current state for {operation.instrument_id}",
                    operation_id=operation.operation_id,
                    point_index=frame.point_index,
                    instrument_id=operation.instrument_id,
                )
            )
            return False
        fields, skipped_count = _changed_state_fields(operation, current=current)
        entry = self.journal.entry(
            operation_id=operation.operation_id,
            stage="apply_state",
            effect="state_write",
            state="started",
            point_index=frame.point_index,
            instrument_id=operation.instrument_id,
            evidence={
                "field_count": len(fields),
                "skipped_field_count": skipped_count,
            },
        )
        if not fields:
            return True
        command = InstrumentStateCommand(
            operation_id=operation.operation_id,
            instrument_id=operation.instrument_id,
            fields=fields,
            payloads=_referenced_payloads(fields, frame.payloads),
        )
        entry = entry.model_copy(
            update={
                "evidence": {
                    **entry.evidence,
                    **command_evidence(command),
                }
            }
        )
        driver = self.drivers[operation.instrument_id]
        receipt = self.journal.invoke(
            entry,
            lambda: driver.apply_state(command),
            unknown_code="instrument_apply_unknown",
            unknown_message=(
                f"instrument apply outcome is unknown for {operation.instrument_id}"
            ),
            unknown_evidence=_state_evidence(
                entry.evidence,
                changed_field_count=0,
                state_command_count=0,
                payload_count=0,
            ),
        )
        if receipt is None:
            return False
        return self._complete_receipt(
            frame=frame,
            operation=operation,
            entry=entry,
            current=current,
            fields=fields,
            command=command,
            receipt=receipt,
            receipt_evidence=apply_receipt_evidence(receipt),
        )

    def _complete_receipt(
        self,
        *,
        frame: PointEffectState,
        operation: ApplyStateOperation,
        entry: ExecutionTransition,
        current: InstrumentStateSnapshot,
        fields: list[InstrumentStateCommandField],
        command: InstrumentStateCommand,
        receipt: ApplyReceipt,
        receipt_evidence: dict[str, JsonValue],
    ) -> bool:
        accepted, receipt_problems = self.journal.accept_receipt(
            entry,
            status=receipt.status,
            success_status="applied",
            problems=receipt.problems,
            evidence={
                **_state_evidence(
                    entry.evidence,
                    changed_field_count=0,
                    state_command_count=0,
                    payload_count=0,
                ),
                "receipt_status": receipt.status,
                **receipt_evidence,
            },
        )
        if not accepted:
            return False
        next_state = receipt.state or apply_state_command_to_snapshot(current, command)
        if next_state.instrument_id != operation.instrument_id:
            problem = self.journal.problem(
                "instrument_apply_state_mismatch",
                "apply receipt state belongs to a different instrument",
                operation_id=operation.operation_id,
                point_index=frame.point_index,
                instrument_id=operation.instrument_id,
            )
            self.journal.problems.append(problem)
            self.journal.indeterminate = True
            self.journal.commit_after_effect(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "problems": (problem,),
                        "evidence": {
                            **_state_evidence(
                                entry.evidence,
                                changed_field_count=0,
                                state_command_count=0,
                                payload_count=0,
                            ),
                            **receipt_evidence,
                        },
                    }
                )
            )
            return False
        self.current_states[operation.instrument_id] = next_state.model_copy(deep=True)
        self.journal.commit_after_effect(
            entry.model_copy(
                update={
                    "state": "completed",
                    "problems": receipt_problems,
                    "evidence": {
                        **_state_evidence(
                            entry.evidence,
                            changed_field_count=len(fields),
                            state_command_count=1,
                            payload_count=len(command.payloads),
                        ),
                        "receipt_status": receipt.status,
                        **receipt_evidence,
                    },
                }
            )
        )
        return True


def _state_evidence(
    base: Mapping[str, JsonValue],
    *,
    changed_field_count: int,
    state_command_count: int,
    payload_count: int,
) -> dict[str, JsonValue]:
    return {
        **base,
        "changed_field_count": changed_field_count,
        "skipped_field_count": base.get("skipped_field_count", 0),
        "state_command_count": state_command_count,
        "payload_count": payload_count,
    }


def _changed_state_fields(
    operation: ApplyStateOperation,
    *,
    current: InstrumentStateSnapshot,
) -> tuple[list[InstrumentStateCommandField], int]:
    current_by_key = {
        _execution_state_target_identity(
            field.capability_id,
            field.field_path,
            field.entity_ids,
            field.channel_bindings,
        ): field.value
        for field in current.fields
    }
    fields: list[InstrumentStateCommandField] = []
    skipped = 0
    for target in operation.targets:
        key = _execution_state_target_identity(
            target.capability_id,
            target.field_path,
            target.entity_ids,
            target.channel_bindings,
        )
        field = target.command_field(resource_id=operation.instrument_id)
        if current_by_key.get(key) == target.value:
            skipped += 1
            continue
        fields.append(field)
    return fields, skipped


def _execution_state_target_identity(
    capability_id: str,
    field_path: str,
    entity_ids: Sequence[str],
    channel_bindings: Sequence[CommandChannelBinding],
) -> tuple[object, ...]:
    return (
        capability_id,
        field_path,
        tuple(entity_ids),
        tuple(
            (
                binding.entity_id,
                binding.channel_id,
                binding.line_id,
                binding.capability,
                tuple(sorted(binding.group_ids)),
            )
            for binding in channel_bindings
        ),
    )


def _referenced_payloads(
    fields: Sequence[InstrumentStateCommandField],
    payloads: Mapping[str, CommandPayload],
) -> dict[str, CommandPayload]:
    referenced: dict[str, CommandPayload] = {}
    for target_field in fields:
        value = target_field.value.root
        if not isinstance(value, PayloadRef):
            continue
        payload = payloads.get(value.payload_id)
        if payload is not None:
            referenced[payload.id] = payload
    return referenced
