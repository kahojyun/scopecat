from __future__ import annotations

from typing import Protocol

import pytest

from scopecat.sdk.instruments import (
    Change,
    DeviceMember,
    DevicePropertyRef,
    DriverOperation,
    DriverStatePatch,
    DriverStateReadRequest,
    DriverSuccess,
    Member,
    ObjectInstrumentDriver,
    device_member,
    instrument_driver,
    query,
    read,
    update,
    write,
)
from scopecat.sdk.instruments.declarations import (
    compile_interface,
    declared_property_ref,
    instrument_interface,
    member,
    operation,
)


@instrument_interface("test.oo_source/v1")
class OOSource(Protocol):
    level: Member[int] = member(access="read_write", minimum=0, maximum=10)
    limit: Member[int] = member(access="read_write", minimum=0, maximum=10)
    serial_number: Member[str] = member(access="read_only", capture=False)

    @operation()
    def zero(self) -> None: ...


@instrument_driver(
    "test.oo_driver",
    "1",
    interfaces=(OOSource,),
    label="OO source",
    device_schema_id="test.oo_source.device/v1",
    device_label="OO source implementation state",
)
class OOSourceDriver(ObjectInstrumentDriver):
    front_panel_locked: DeviceMember[bool] = device_member(
        access="read_write",
        description="Local front-panel lock state",
    )

    def __init__(self) -> None:
        self.instrument_id = "source"
        self._level = 3
        self._limit = 8
        self._front_panel_locked = False
        self.zero_count = 0

    @query(OOSource.level, OOSource.limit, OOSource.serial_number)
    def query_state(self) -> tuple[int, int, str]:
        return self._level, self._limit, "SN-1"

    @update(OOSource.level, OOSource.limit)
    def update_state(
        self,
        *,
        level: Change[int],
        limit: Change[int],
    ) -> None:
        if level.requested:
            self._level = level.value
        if limit.requested:
            self._limit = limit.value

    @read(front_panel_locked)
    def read_front_panel_locked(self) -> bool:
        return self._front_panel_locked

    @write(front_panel_locked)
    def write_front_panel_locked(self, value: bool) -> None:
        self._front_panel_locked = value

    def zero(self) -> None:
        self._level = 0
        self.zero_count += 1


def test_member_attributes_compile_without_property_inference() -> None:
    spec = compile_interface(OOSource).spec

    assert [
        (item.id, item.access, item.capture, item.restore) for item in spec.properties
    ] == [
        ("level", "read_write", True, True),
        ("limit", "read_write", True, True),
        ("serial_number", "read_only", False, False),
    ]


def test_object_driver_adapts_properties_and_methods() -> None:
    driver = OOSourceDriver()
    level = declared_property_ref(OOSource, "level")
    limit = declared_property_ref(OOSource, "limit")
    serial_number = declared_property_ref(OOSource, "serial_number")

    assert driver.describe().interfaces == [compile_interface(OOSource).spec]
    readback = driver.read_state(DriverStateReadRequest(frozenset({level})))
    assert readback.values == {
        level: 3,
        limit: 8,
        serial_number: "SN-1",
    }
    coherence_ids = {observation.coherence_id for observation in readback.observations}
    assert len(coherence_ids) == 1
    assert coherence_ids != {None}

    applied = driver.apply_state(DriverStatePatch(values={level: 7}))
    assert applied == DriverSuccess(None)
    assert driver._level == 7

    invoked = driver.invoke(
        DriverOperation(target=compile_interface(OOSource).ref.operation("zero"))
    )
    assert invoked == DriverSuccess(None)
    assert driver._level == 0
    assert driver.zero_count == 1


def test_object_driver_captures_and_restores_device_owned_properties() -> None:
    driver = OOSourceDriver()
    target = DevicePropertyRef(
        "test.oo_source.device/v1",
        (),
        "front_panel_locked",
    )

    description = driver.describe()
    [device_schema] = description.device_schemas
    assert device_schema.id == "test.oo_source.device/v1"
    assert device_schema.members[0].property.restore is True
    assert driver.read_state(DriverStateReadRequest(frozenset({target}))).values == {
        target: False
    }

    assert driver.apply_state(DriverStatePatch(values={target: True})) == DriverSuccess(
        None
    )
    assert driver._front_panel_locked is True


def test_driver_declaration_requires_complete_member_io_bindings() -> None:
    @instrument_interface("test.missing_bindings/v1")
    class MissingBindings(Protocol):
        value: Member[int] = member(access="read_write")

    with pytest.raises(TypeError, match="no reader"):

        @instrument_driver(
            "test.missing_bindings",
            "1",
            interfaces=(MissingBindings,),
        )
        class MissingBindingsDriver(  # pyright: ignore[reportUnusedClass]
            ObjectInstrumentDriver
        ):
            pass
