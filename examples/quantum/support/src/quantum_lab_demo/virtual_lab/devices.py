"""Virtual devices that own offline physical state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scopecat.instruments import (
    DriverFault,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    PayloadRef,
    StateValue,
)
from scopecat.models.parameter import Quantity
from scopecat.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)

from quantum_lab_demo.virtual_lab.models import VirtualDeviceProfile


@dataclass(frozen=True)
class VirtualPatchRecord:
    instrument_id: str
    capability_id: str
    field_path: str
    before: StateValue | None
    after: StateValue


class VirtualDevice:
    """Stateful offline device behind the instrument provider boundary."""

    def __init__(self, profile: VirtualDeviceProfile) -> None:
        self.id = profile.id
        self.kind = profile.kind
        self.response_model_id = profile.response_model_id
        self.metadata = dict(profile.metadata)
        self._state = {
            _decode_state_key(key): value
            for key, value in profile.initial_state.items()
        }
        self._patch_log: list[VirtualPatchRecord] = []

    @property
    def patch_log(self) -> tuple[VirtualPatchRecord, ...]:
        return tuple(self._patch_log)

    @property
    def state(self) -> dict[tuple[str, str], StateValue]:
        return dict(self._state)

    def apply(self, command: InstrumentStateCommand) -> None:
        if command.instrument_id != self.id:
            raise DriverFault(
                blocking_problem(
                    "virtual_lab_device_mismatch",
                    f"{self.id} cannot apply command for {command.instrument_id}",
                    category=ProblemCategory.PROVIDER_CONTRACT,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location(
                        "instrument_state_command", "instrument_id"
                    ),
                )
            )
        for field in command.fields:
            self._apply_field(field)

    def quantity(self, capability_id: str, field_path: str) -> Quantity | None:
        value = self._state.get((capability_id, field_path))
        if value is None or not isinstance(value.root, Quantity):
            return None
        return value.root

    def number(self, capability_id: str, field_path: str) -> float | None:
        value = self._state.get((capability_id, field_path))
        if value is None or not isinstance(value.root, float):
            return None
        return value.root

    def payload_id(self, capability_id: str, field_path: str) -> str | None:
        value = self._state.get((capability_id, field_path))
        if value is None or not isinstance(value.root, PayloadRef):
            return None
        return value.root.payload_id

    def measurement_metadata(self) -> dict[str, Any]:
        payloads: dict[str, str] = {}
        for (capability_id, field_path), value in self._state.items():
            if isinstance(value.root, PayloadRef):
                payloads[_encode_state_key(capability_id, field_path)] = (
                    value.root.payload_id
                )
        return {
            "virtual_device": self.id,
            "virtual_device_kind": self.kind,
            "virtual_payloads": payloads,
            "applied_patch_count": len(self._patch_log),
        }

    def _apply_field(self, field: InstrumentStateCommandField) -> None:
        key = (field.capability_id, field.field_path)
        before = self._state.get(key)
        self._state[key] = field.value
        self._patch_log.append(
            VirtualPatchRecord(
                instrument_id=self.id,
                capability_id=field.capability_id,
                field_path=field.field_path,
                before=before,
                after=field.value,
            )
        )


class VirtualLab:
    def __init__(self, devices: dict[str, VirtualDevice]) -> None:
        self._devices = devices

    @classmethod
    def from_profiles(cls, profiles: list[VirtualDeviceProfile]) -> VirtualLab:
        return cls({profile.id: VirtualDevice(profile) for profile in profiles})

    def device(self, device_id: str) -> VirtualDevice:
        try:
            return self._devices[device_id]
        except KeyError as error:
            raise DriverFault(
                blocking_problem(
                    "virtual_lab_missing_device",
                    f"virtual lab profile does not define {device_id}",
                    category=ProblemCategory.PROVIDER_CONTRACT,
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("virtual_lab_profile", "devices"),
                    details={"device_id": device_id},
                )
            ) from error

    @property
    def devices(self) -> tuple[VirtualDevice, ...]:
        return tuple(self._devices.values())


def _decode_state_key(key: str) -> tuple[str, str]:
    capability_id, separator, field_path = key.partition(".")
    if not separator or not capability_id or not field_path:
        raise ValueError(
            "virtual device initial_state keys must use '<capability_id>.<field_path>'"
        )
    return capability_id, field_path


def _encode_state_key(capability_id: str, field_path: str) -> str:
    return f"{capability_id}.{field_path}"


__all__ = ["VirtualDevice", "VirtualLab", "VirtualPatchRecord"]
