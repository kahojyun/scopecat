"""Runtime desired-state diff and driver command construction."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.experiments import (
    PointRouteBinding,
    ProgramResourceState,
    ProgramStateValue,
)
from scopecat.instruments.sdk import (
    CommandChannelBinding,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    InstrumentStateSnapshot,
    apply_state_command_to_snapshot,
    validate_state_command,
)
from scopecat.instruments.state import StateValue
from scopecat.models.artifact import CommandPayload
from scopecat.models.config import RoutingChannelBinding
from scopecat.planning.validation import has_blocking_diagnostics


@dataclass(frozen=True)
class StateApplySummary:
    changed_field_count: int = 0
    skipped_field_count: int = 0
    state_command_count: int = 0
    payload_count: int = 0

    def merged(self, other: StateApplySummary) -> StateApplySummary:
        return StateApplySummary(
            changed_field_count=self.changed_field_count + other.changed_field_count,
            skipped_field_count=self.skipped_field_count + other.skipped_field_count,
            state_command_count=self.state_command_count + other.state_command_count,
            payload_count=self.payload_count + other.payload_count,
        )


@dataclass(frozen=True)
class _StateCommandPlan:
    command: InstrumentStateCommand
    skipped_field_count: int


def apply_desired_state(
    *,
    desired: list[ProgramResourceState],
    current_states: dict[str, InstrumentStateSnapshot],
    instruments_by_id: dict[str, InstrumentDriver],
    descriptions_by_id: dict[str, InstrumentDescription],
    payloads: dict[str, CommandPayload],
    route_bindings: list[PointRouteBinding],
    diagnostics: list[Diagnostic],
) -> StateApplySummary:
    summary = StateApplySummary()
    for resource in desired:
        instrument = instruments_by_id[resource.resource_id]
        current = current_states.get(resource.resource_id)
        if current is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "missing_current_state",
                    f"missing current state for {resource.resource_id}",
                    resource.resource_id,
                )
            )
            continue
        description = descriptions_by_id.get(resource.resource_id)
        if description is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "missing_instrument_description",
                    f"instrument {resource.resource_id} did not provide a description",
                    "instruments",
                )
            )
            continue
        command_plan = state_command_for_resource(
            current=current,
            desired=resource,
            payloads=payloads,
            route_bindings=route_bindings,
        )
        command = command_plan.command
        command_diagnostics = validate_state_command(
            command=command,
            description=description,
            payloads=payloads,
        )
        diagnostics.extend(command_diagnostics)
        if has_blocking_diagnostics(command_diagnostics):
            continue
        if not command.fields:
            summary = summary.merged(
                StateApplySummary(
                    skipped_field_count=command_plan.skipped_field_count,
                )
            )
            continue
        try:
            result = instrument.apply_state(command)
        except Exception as error:
            diagnostics.append(
                _diagnostic_from_exception(
                    "error",
                    "instrument_apply_failed",
                    "instrument apply failed for "
                    f"{resource.resource_id}: {type(error).__name__}: {error}",
                    resource.resource_id,
                    error,
                )
            )
            continue
        diagnostics.extend(result.diagnostics)
        summary = summary.merged(
            StateApplySummary(
                changed_field_count=len(command.fields),
                skipped_field_count=command_plan.skipped_field_count,
                state_command_count=1,
                payload_count=len(command.payloads),
            )
        )
        current_states[resource.resource_id] = apply_state_command_to_snapshot(
            current, command
        )
    return summary


def state_command_for_resource(
    *,
    current: InstrumentStateSnapshot,
    desired: ProgramResourceState,
    payloads: dict[str, CommandPayload],
    route_bindings: list[PointRouteBinding],
) -> _StateCommandPlan:
    current_by_key = {
        (field.capability_id, field.field_path): field.value for field in current.fields
    }
    command_fields: list[InstrumentStateCommandField] = []
    skipped_field_count = 0
    for field in desired.fields:
        key = (desired.capability_id, field.field_path)
        field_value = driver_state_value(field.value)
        if not field.channel_bindings and current_by_key.get(key) == field_value:
            skipped_field_count += 1
            continue
        command_fields.append(
            InstrumentStateCommandField(
                resource_id=desired.resource_id,
                capability_id=desired.capability_id,
                field_path=field.field_path,
                value=field_value,
                channel_bindings=(
                    [
                        command_channel_binding(binding)
                        for binding in field.channel_bindings
                    ]
                    or command_channel_bindings(
                        resource_id=desired.resource_id,
                        capability_id=desired.capability_id,
                        route_bindings=route_bindings,
                    )
                ),
            )
        )
    return _StateCommandPlan(
        command=InstrumentStateCommand(
            instrument_id=desired.resource_id,
            fields=command_fields,
            payloads=_referenced_command_payloads(command_fields, payloads),
        ),
        skipped_field_count=skipped_field_count,
    )


def driver_state_value(value: ProgramStateValue) -> StateValue:
    return StateValue.model_validate(value.model_dump(mode="python"))


def command_channel_bindings(
    *,
    resource_id: str,
    capability_id: str | None,
    route_bindings: list[PointRouteBinding],
) -> list[CommandChannelBinding]:
    selected: list[CommandChannelBinding] = []
    for route in route_bindings:
        if route.resource_id != resource_id:
            continue
        if capability_id is not None and capability_id not in route.capabilities:
            continue
        for binding in route.channel_bindings:
            if (
                capability_id is not None
                and binding.capability is not None
                and binding.capability != capability_id
            ):
                continue
            selected.append(command_channel_binding(binding))
    return selected


def command_channel_binding(binding: RoutingChannelBinding) -> CommandChannelBinding:
    return CommandChannelBinding(
        entity_id=binding.entity_id,
        channel_id=binding.channel_id,
        line_id=binding.line_id,
        capability=binding.capability,
        group_ids=list(binding.group_ids),
        metadata=dict(binding.metadata),
    )


def _referenced_command_payloads(
    fields: list[InstrumentStateCommandField],
    payloads: dict[str, CommandPayload],
) -> dict[str, CommandPayload]:
    referenced: dict[str, CommandPayload] = {}
    for field in fields:
        if field.value.kind != "payload" or field.value.payload_id is None:
            continue
        payload = payloads.get(field.value.payload_id)
        if payload is not None:
            referenced[payload.id] = payload
    return referenced


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


def _diagnostic_from_exception(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None,
    error: Exception,
) -> Diagnostic:
    to_diagnostic = getattr(error, "to_diagnostic", None)
    if callable(to_diagnostic):
        diagnostic = to_diagnostic()
        if isinstance(diagnostic, Diagnostic):
            return diagnostic
    return _diagnostic(severity, code, message, path)


__all__ = [
    "StateApplySummary",
    "apply_desired_state",
    "command_channel_binding",
    "command_channel_bindings",
    "driver_state_value",
    "state_command_for_resource",
]
