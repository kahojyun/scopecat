from __future__ import annotations

from typing import Protocol

from scopecat.sdk.instruments import (
    DriverOperation,
    DriverStatePatch,
    DriverStateReadRequest,
    DriverSuccess,
    ObjectInstrumentDriver,
    instrument_driver,
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
    @property
    @member(minimum=0, maximum=10)
    def level(self) -> int: ...

    @level.setter
    def level(self, value: int) -> None: ...

    @property
    @member(capture=False)
    def serial_number(self) -> str: ...

    @operation()
    def zero(self) -> None: ...


@instrument_driver(
    "test.oo_driver",
    "1",
    interfaces=(OOSource,),
    label="OO source",
)
class OOSourceDriver(ObjectInstrumentDriver):
    def __init__(self) -> None:
        self.instrument_id = "source"
        self._level = 3
        self.zero_count = 0

    @property
    def level(self) -> int:
        return self._level

    @level.setter
    def level(self, value: int) -> None:
        self._level = value

    @property
    def serial_number(self) -> str:
        return "SN-1"

    def zero(self) -> None:
        self._level = 0
        self.zero_count += 1


def test_property_members_compile_from_normal_python_properties() -> None:
    spec = compile_interface(OOSource).spec

    assert [
        (item.id, item.access, item.capture, item.restore) for item in spec.properties
    ] == [
        ("level", "read_write", True, True),
        ("serial_number", "read_only", False, False),
    ]


def test_object_driver_adapts_properties_and_methods() -> None:
    driver = OOSourceDriver()
    level = declared_property_ref(OOSource, "level")

    assert driver.describe().interfaces == [compile_interface(OOSource).spec]
    assert driver.read_state(DriverStateReadRequest(frozenset({level}))).values == {
        level: 3
    }

    applied = driver.apply_state(DriverStatePatch(values={level: 7}))
    assert applied == DriverSuccess(None)
    assert driver.level == 7

    invoked = driver.invoke(
        DriverOperation(target=compile_interface(OOSource).ref.operation("zero"))
    )
    assert invoked == DriverSuccess(None)
    assert driver.level == 0
    assert driver.zero_count == 1
