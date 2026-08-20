from __future__ import annotations

from typing import override

from scopecat.kernel.value_types import Int, Scalar
from scopecat.records.instrument import state_member_target
from scopecat.records.measurement import MeasurementScalar
from scopecat.sdk.instruments import (
    AcquisitionRef,
    DevicePropertyRef,
    DeviceStateMemberSpec,
    DeviceStateSpec,
    DriverAcquisition,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverStateObservation,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    DriverUnknown,
    InstrumentDescription,
    InterfacePropertyImplementationSpec,
    InterfaceRef,
    MountedInstrumentDriver,
    MountedInstrumentRouter,
    PropertyRef,
    StatePropertyRef,
    acquisition,
    acquisition_result,
    bool_property,
    int_property,
    interface,
    operation,
    state_capture_request,
)
from scopecat.sdk.instruments.contracts import resolve_state_member_spec
from scopecat.sdk.problems import ProblemPhase, problem

_INTERFACE = InterfaceRef("test.mounted_child/v1")
_VALUE = _INTERFACE.property("value")
_ZERO = _INTERFACE.operation("zero")
_SAMPLE = _INTERFACE.acquisition("sample")
_RESULT = _SAMPLE.result("value")
_LOCKED = DevicePropertyRef("test.mounted_child.device/v1", (), "locked")


class _ChildDriver:
    implementation_id = "test.mounted_child"
    implementation_version = "1"

    def __init__(
        self,
        instrument_id: str,
        value: int,
        *,
        reject_apply: bool = False,
        device_schema_id: str = "test.mounted_child.device/v1",
        read_only: bool = False,
    ):
        self.instrument_id = instrument_id
        self.value = value
        self.locked = False
        self.locked_ref = DevicePropertyRef(device_schema_id, (), "locked")
        self.reject_apply = reject_apply
        self.read_only = read_only
        self.state_requests: list[DriverStateReadRequest] = []
        self.state_patches: list[DriverStatePatch] = []
        self.operations: list[DriverOperation] = []
        self.acquisitions: list[DriverAcquisition] = []

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=[
                interface(
                    _INTERFACE.interface_id,
                    properties=[int_property("value")],
                    operations=[operation("zero")],
                    acquisitions=[
                        acquisition(
                            "sample",
                            results=[acquisition_result("value")],
                        )
                    ],
                )
            ],
            device_schemas=[
                DeviceStateSpec(
                    id=self.locked_ref.schema_id,
                    members=[
                        DeviceStateMemberSpec(
                            property=bool_property("locked"),
                        )
                    ],
                )
            ],
            interface_property_implementations=(
                [
                    InterfacePropertyImplementationSpec(
                        property=StatePropertyRef(
                            interface_id=_INTERFACE.interface_id,
                            property_id="value",
                        ),
                        access="read_only",
                        capture=True,
                        restore=False,
                        value_type=Scalar(Int(minimum=0, maximum=10)),
                    )
                ]
                if self.read_only
                else []
            ),
        )

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        self.state_requests.append(request)
        values = {_VALUE: self.value, self.locked_ref: self.locked}
        return DriverStateReadback(
            observations=tuple(
                DriverStateObservation(
                    target,
                    values[target],
                    coherence_id="child-query",
                    entity_ids=("entity",),
                    metadata={"child": self.instrument_id},
                )
                for target in request.targets
            ),
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        self.state_patches.append(request)
        if self.reject_apply:
            return DriverRejected(
                problems=(
                    problem(
                        "child_rejected",
                        "child rejected state",
                        phase=ProblemPhase.EXECUTION,
                    ),
                )
            )
        for entry in request.entries:
            if entry.target == _VALUE:
                assert isinstance(entry.value, int) and not isinstance(
                    entry.value, bool
                )
                self.value = entry.value
            elif entry.target == self.locked_ref:
                assert isinstance(entry.value, bool)
                self.locked = entry.value
        return DriverSuccess(None)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        self.operations.append(request)
        self.value = 0
        return DriverSuccess(
            DriverStateReadback(
                observations=(DriverStateObservation(_VALUE, self.value),)
            )
        )

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        self.acquisitions.append(request)
        return DriverSuccess(
            DriverReadback(
                values={
                    result: MeasurementScalar.create(
                        dtype="float64",
                        value=float(self.value),
                    )
                    for result in request.results
                },
                metadata={"sampled": True},
            )
        )

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        return None


class _MountedDevice(MountedInstrumentDriver):
    implementation_id = "test.mounted"
    implementation_version = "1"

    def __init__(self, child: _ChildDriver) -> None:
        super().__init__(
            "device",
            mounts={("channels", "1"): child},
            label="Mounted device",
        )

    @override
    def _state_metadata(self) -> dict[str, bool]:
        return {"identified": True}

    @override
    def disconnect(self) -> None:
        return None

    @override
    def abort(self) -> None:
        return None


def _mounted_property(target: PropertyRef, channel: str) -> PropertyRef:
    return PropertyRef(
        target.interface_id,
        ("channels", channel),
        target.property_id,
    )


def _router(*children: _ChildDriver) -> MountedInstrumentRouter:
    return MountedInstrumentRouter(
        instrument_id="device",
        implementation_id="test.mounted",
        implementation_version="1",
        mounts={
            ("channels", str(index)): child
            for index, child in enumerate(children, start=1)
        },
    )


def test_mounted_router_composes_contracts_and_preserves_observation_provenance() -> (
    None
):
    first = _ChildDriver("child-1", 1)
    second = _ChildDriver("child-2", 2)
    router = _router(first, second)
    first_mounted_value = _mounted_property(_VALUE, "1")
    mounted_value = _mounted_property(_VALUE, "2")

    description = router.describe()
    readback = router.read_state(
        DriverStateReadRequest(frozenset({first_mounted_value, mounted_value}))
    )

    assert [component.id for component in description.components] == ["channels"]
    assert [component.id for component in description.components[0].components] == [
        "1",
        "2",
    ]
    assert {tuple(mount.component_path) for mount in description.interface_mounts} == {
        ("channels", "1"),
        ("channels", "2"),
    }
    [device_schema] = description.device_schemas
    assert {tuple(member.component_path) for member in device_schema.members} == {
        ("channels", "1"),
        ("channels", "2"),
    }
    assert state_capture_request(description).targets == {
        _mounted_property(_VALUE, "1"),
        _mounted_property(_VALUE, "2"),
        DevicePropertyRef(_LOCKED.schema_id, ("channels", "1"), "locked"),
        DevicePropertyRef(_LOCKED.schema_id, ("channels", "2"), "locked"),
    }
    observations = {
        observation.target: observation for observation in readback.observations
    }
    assert observations[mounted_value].coherence_id == "child-query"
    assert observations[mounted_value].entity_ids == ("entity",)
    assert observations[first_mounted_value].metadata == {"child": "child-1"}
    assert observations[mounted_value].metadata == {"child": "child-2"}
    assert first.state_requests == [DriverStateReadRequest(frozenset({_VALUE}))]
    assert second.state_requests == [DriverStateReadRequest(frozenset({_VALUE}))]


def test_mounted_router_routes_commands_and_marks_partial_apply_unknown() -> None:
    first = _ChildDriver("child-1", 1)
    second = _ChildDriver("child-2", 2, reject_apply=True)
    router = _router(first, second)

    outcome = router.apply_state(
        DriverStatePatch(
            values={
                _mounted_property(_VALUE, "1"): 10,
                _mounted_property(_VALUE, "2"): 20,
            }
        )
    )

    assert isinstance(outcome, DriverUnknown)
    assert outcome.problems[0].code == "instrument_partial_apply_outcome_unknown"
    assert outcome.problems[0].details == {
        "completed_mounts": ("channels/1",),
        "failed_mount": "channels/2",
        "failure_codes": ("child_rejected",),
    }
    assert first.value == 10

    mounted_operation = DriverOperation(
        target=type(_ZERO)(
            _ZERO.interface_id,
            ("channels", "1"),
            _ZERO.operation_id,
        )
    )
    invoked = router.invoke(mounted_operation)
    assert isinstance(invoked, DriverSuccess)
    assert invoked.value is not None
    assert invoked.value.observations[0].target == _mounted_property(_VALUE, "1")
    assert first.operations[0].target == _ZERO

    mounted_acquisition = AcquisitionRef(
        _SAMPLE.interface_id,
        ("channels", "1"),
        _SAMPLE.acquisition_id,
    )
    mounted_result = mounted_acquisition.result(_RESULT.result_id)
    collected = router.collect(
        DriverAcquisition(
            target=mounted_acquisition,
            results=frozenset({mounted_result}),
        )
    )
    assert isinstance(collected, DriverSuccess)
    assert set(collected.value.values) == {mounted_result}
    assert first.acquisitions[0].target == _SAMPLE
    assert first.acquisitions[0].results == {_RESULT}


def test_mounted_router_preserves_per_endpoint_property_implementations() -> None:
    router = _router(
        _ChildDriver("child-1", 1),
        _ChildDriver("child-2", 2, read_only=True),
    )

    description = router.describe()
    first = _mounted_property(_VALUE, "1")
    second = _mounted_property(_VALUE, "2")
    first_spec = resolve_state_member_spec(description, state_member_target(first))
    second_spec = resolve_state_member_spec(description, state_member_target(second))

    [implementation] = description.interface_property_implementations
    assert implementation.property.component_path == ["channels", "2"]
    assert first_spec is not None and first_spec.access == "read_write"
    assert second_spec is not None and second_spec.access == "read_only"
    assert second_spec.value_type == Scalar(Int(minimum=0, maximum=10))


def test_mounted_router_keeps_multiple_device_schemas_distinct() -> None:
    first = _ChildDriver("child-1", 1)
    second = _ChildDriver(
        "child-2",
        2,
        device_schema_id="test.other_child.device/v1",
    )

    description = _router(first, second).describe()

    assert [schema.id for schema in description.device_schemas] == [
        "test.mounted_child.device/v1",
        "test.other_child.device/v1",
    ]
    assert {
        (schema.id, tuple(member.component_path), member.property.id)
        for schema in description.device_schemas
        for member in schema.members
    } == {
        ("test.mounted_child.device/v1", ("channels", "1"), "locked"),
        ("test.other_child.device/v1", ("channels", "2"), "locked"),
    }


def test_mounted_driver_declares_mounts_once_and_adds_physical_metadata() -> None:
    child = _ChildDriver("child-1", 1)
    driver = _MountedDevice(child)
    target = _mounted_property(_VALUE, "1")

    readback = driver.read_state(DriverStateReadRequest(frozenset({target})))

    assert driver.describe().label == "Mounted device"
    assert readback.values == {target: 1}
    [observation] = readback.observations
    assert observation.metadata == {
        "child": "child-1",
        "identified": True,
    }
