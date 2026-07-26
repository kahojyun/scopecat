"""Virtual devices that own offline physical state."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    DriverFault,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    StateValue,
)
from scopecat.sdk.problems import (
    ProblemPhase,
    model_location,
    problem,
)

from quantum_lab_demo.virtual_lab.models import VirtualDeviceProfile


class VirtualDevice:
    """Stateful offline device behind the instrument provider boundary."""

    def __init__(self, profile: VirtualDeviceProfile) -> None:
        self.id = profile.id
        self._state = {
            _decode_state_key(key): value
            for key, value in profile.initial_state.items()
        }

    @property
    def state(self) -> dict[tuple[str, str], StateValue]:
        return dict(self._state)

    def apply(self, command: InstrumentStateCommand) -> None:
        if command.instrument_id != self.id:
            raise DriverFault(
                problem(
                    "virtual_lab_device_mismatch",
                    f"{self.id} cannot apply command for {command.instrument_id}",
                    phase=ProblemPhase.EXECUTION,
                    location=model_location(
                        "instrument_state_command", "instrument_id"
                    ),
                )
            )
        for field in command.fields:
            self._apply_field(field)

    def _apply_field(self, field: InstrumentStateCommandField) -> None:
        key = (field.capability_id, field.field_path)
        self._state[key] = field.value


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
                problem(
                    "virtual_lab_missing_device",
                    f"virtual lab profile does not define {device_id}",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("virtual_lab_profile", "devices"),
                    details={"device_id": device_id},
                )
            ) from error


def _decode_state_key(key: str) -> tuple[str, str]:
    capability_id, separator, field_path = key.partition(".")
    if not separator or not capability_id or not field_path:
        raise ValueError(
            "virtual device initial_state keys must use '<capability_id>.<field_path>'"
        )
    return capability_id, field_path


__all__ = ["VirtualDevice", "VirtualLab"]
