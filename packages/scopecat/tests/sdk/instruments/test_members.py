from __future__ import annotations

from collections.abc import Callable
from typing import assert_type

import pytest

from scopecat.sdk.instruments import (
    AcquisitionRef,
    AcquisitionResultRef,
    ComponentRef,
    InterfaceRef,
    OperationRef,
    PropertyRef,
)


def test_member_factories_preserve_the_complete_physical_scope() -> None:
    interface = InterfaceRef("test.vector_source/v2")
    output = assert_type(interface.component("output"), ComponentRef)
    channel = assert_type(output.component("channel-a"), ComponentRef)
    level = assert_type(channel.property("level"), PropertyRef)
    reset = assert_type(channel.operation("reset"), OperationRef)
    sample = assert_type(channel.acquisition("sample"), AcquisitionRef)
    signal = assert_type(sample.result("signal"), AcquisitionResultRef)

    assert interface.property("enabled") == PropertyRef(
        "test.vector_source/v2",
        (),
        "enabled",
    )
    assert channel.component_path == ("output", "channel-a")
    assert level.component_path == channel.component_path
    assert reset.component_path == channel.component_path
    assert signal.acquisition == sample


def test_member_references_are_stable_mapping_keys() -> None:
    level = InterfaceRef("test.source/v1").property("level")
    values = {level: 1.25}

    assert values[PropertyRef("test.source/v1", (), "level")] == 1.25


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: InterfaceRef("source"), "instrument interface ids"),
        (lambda: ComponentRef("test.source/v1", ()), "component path"),
        (
            lambda: ComponentRef("test.source/v1", ("",)),
            "component id must be non-empty",
        ),
        (
            lambda: PropertyRef("test.source/v1", (), ""),
            "property id must be non-empty",
        ),
        (
            lambda: OperationRef("test.source/v1", (), ""),
            "operation id must be non-empty",
        ),
        (
            lambda: AcquisitionRef("test.source/v1", (), ""),
            "acquisition id must be non-empty",
        ),
        (
            lambda: AcquisitionResultRef("test.source/v1", (), "sample", ""),
            "acquisition result id must be non-empty",
        ),
    ],
)
def test_member_references_reject_invalid_identities(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
