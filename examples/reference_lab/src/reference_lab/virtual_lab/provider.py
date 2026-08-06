"""Instrument providers backed by configurable virtual devices."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, cast

from pydantic import JsonValue
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverCatalog,
    DriverConnectionSpec,
    DriverFault,
    DriverOperation,
    DriverOutcome,
    DriverPayload,
    DriverReadback,
    DriverScalar,
    DriverSpec,
    DriverState,
    DriverStatePatch,
    DriverSuccess,
    InstrumentBindingSpec,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InterfaceSpec,
    PropertyRef,
    VirtualInstrumentConnection,
)
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)

from reference_lab.interfaces import (
    acquire_iq_interface,
    play_pulse_program_interface,
    readout_pulse_interface,
)
from reference_lab.payloads import DecodedPulseProgram
from reference_lab.virtual_lab.models import VirtualDeviceProfile
from reference_lab.virtual_lab.profiles import load_virtual_lab_profile

_DRIVE_STACK_DRIVER_ID = "reference_lab.virtual_lab.drive_stack"
_READOUT_STACK_DRIVER_ID = "reference_lab.virtual_lab.readout_stack"


class _VirtualInstrumentDriver:
    _implementation_id: ClassVar[str]

    def __init__(
        self,
        *,
        profile: VirtualDeviceProfile,
        interfaces: Sequence[InterfaceSpec],
    ) -> None:
        self.instrument_id = profile.id
        self.implementation_id = self._implementation_id
        self.implementation_version = "v0"
        self._interfaces = list(interfaces)
        self._metadata: dict[str, JsonValue] = {
            "mode": "virtual_lab",
            "source": "reference-lab",
        }
        self._state = {
            _decode_property_key(key): cast("DriverScalar", value.root)
            for key, value in profile.seed_state.items()
        }

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=list(self._interfaces),
        )

    def read_state(self) -> DriverState:
        return DriverState(
            values={
                PropertyRef(interface_id, (), property_id): value
                for (interface_id, property_id), value in self._state.items()
            },
            metadata=self._metadata,
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        for target, value in request.values.items():
            self._state[(target.interface_id, target.property_id)] = value
        return DriverSuccess(None)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        programs = tuple(
            cast("DecodedPulseProgram", argument.value)
            for argument in request.arguments.values()
            if isinstance(argument, DriverPayload)
        )
        documents = tuple(program.document for program in programs)
        return DriverSuccess(
            None,
            metadata={
                "interface_id": request.target.interface_id,
                "operation_id": request.target.operation_id,
                "payload_count": len(documents),
            },
        )

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        del request
        return DriverSuccess(DriverReadback(values={}))

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        return None


class QuantumDriveStack(_VirtualInstrumentDriver):
    _implementation_id = _DRIVE_STACK_DRIVER_ID

    def __init__(self, *, profile: VirtualDeviceProfile) -> None:
        super().__init__(
            profile=profile,
            interfaces=[play_pulse_program_interface()],
        )


class QuantumReadoutStack(_VirtualInstrumentDriver):
    _implementation_id = _READOUT_STACK_DRIVER_ID

    def __init__(self, *, profile: VirtualDeviceProfile) -> None:
        super().__init__(
            profile=profile,
            interfaces=[
                readout_pulse_interface(),
                acquire_iq_interface(),
            ],
        )


class QuantumLabVirtualProvider:
    provider_id = "reference_lab.virtual_lab.provider"
    driver_catalog = DriverCatalog(
        provider_id=provider_id,
        drivers=(
            DriverSpec(
                driver_id=_DRIVE_STACK_DRIVER_ID,
                implementation_version="v0",
                label="Virtual quantum drive stack",
                connections=(
                    DriverConnectionSpec(
                        kind="virtual",
                        options_schema={
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    ),
                ),
            ),
            DriverSpec(
                driver_id=_READOUT_STACK_DRIVER_ID,
                implementation_version="v0",
                label="Virtual quantum readout stack",
                connections=(
                    DriverConnectionSpec(
                        kind="virtual",
                        options_schema={
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    ),
                ),
            ),
        ),
    )

    def __init__(
        self,
        profile: str | Path,
    ) -> None:
        self.profile = load_virtual_lab_profile(profile)

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        problems: list[Problem] = []
        instruments: list[InstrumentDescription] = []
        for binding in context.bindings:
            try:
                instruments.append(self._build_virtual_instrument(binding).describe())
            except DriverFault as error:
                problems.append(error.problem)
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(instruments),
            problems=tuple(problems),
        )

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver:
        return self._build_virtual_instrument(context.binding)

    def _build_virtual_instrument(
        self,
        binding: InstrumentBindingSpec,
    ) -> InstrumentDriver:
        if not isinstance(binding.connection, VirtualInstrumentConnection):
            raise DriverFault(
                problem(
                    "virtual_lab_connection_invalid",
                    f"{binding.id} requires a virtual connection",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location(
                        "instrument_connection",
                        "binding",
                        "connection",
                    ),
                    details={"instrument_id": binding.id},
                )
            )
        profiles = {profile.id: profile for profile in self.profile.devices}
        profile = _required_profile(profiles, binding.id)
        if binding.driver_id == _DRIVE_STACK_DRIVER_ID:
            return QuantumDriveStack(profile=profile)
        if binding.driver_id == _READOUT_STACK_DRIVER_ID:
            return QuantumReadoutStack(profile=profile)
        raise DriverFault(
            problem(
                "virtual_lab_unknown_driver",
                f"virtual lab does not support driver {binding.driver_id}",
                phase=ProblemPhase.PROVIDER_PREFLIGHT,
                location=model_location(
                    "instrument_connection",
                    "binding",
                    "driver_id",
                ),
                details={
                    "instrument_id": binding.id,
                    "driver_id": binding.driver_id,
                },
            ),
        )


def _required_profile(
    profiles: dict[str, VirtualDeviceProfile],
    device_id: str,
) -> VirtualDeviceProfile:
    try:
        return profiles[device_id]
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


def _decode_property_key(key: str) -> tuple[str, str]:
    interface_id, separator, property_id = key.partition("::")
    if not separator or not interface_id or not property_id:
        raise ValueError(
            "virtual device seed_state keys must use '<interface_id>::<property_id>'"
        )
    return interface_id, property_id


__all__ = [
    "QuantumDriveStack",
    "QuantumLabVirtualProvider",
    "QuantumReadoutStack",
]
