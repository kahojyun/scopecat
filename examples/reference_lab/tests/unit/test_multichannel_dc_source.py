from __future__ import annotations

from scopecat import Quantity
from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments import (
    DriverOperation,
    DriverStateEntry,
    DriverStatePatch,
    DriverSuccess,
)
from scopecat_instruments.members import (
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE,
)
from scopecat_instruments.virtual import VirtualLabWorld

from reference_lab.provider import MultiChannelVirtualDcSource


def _binding(entity_id: str, channel_id: str) -> CommandChannelBinding:
    return CommandChannelBinding(
        entity_id=entity_id,
        channel_id=channel_id,
        interface_id="scopecat.dc_source/v3",
    )


def test_two_channels_keep_independent_levels_and_abort_together() -> None:
    world = VirtualLabWorld(seed=5)
    driver = MultiChannelVirtualDcSource(
        "flux-dac-a",
        world,
    )
    bindings = (
        _binding("q0", "flux.dac_a.ch1"),
        _binding("q1", "flux.dac_a.ch2"),
    )

    for binding, level in zip(bindings, (-0.08, 0.06), strict=True):
        outcome = driver.invoke(
            DriverOperation(
                target=DC_SOURCE_VOLTAGE,
                arguments={
                    "range": Quantity(1.0, "V"),
                    "level": Quantity(level, "V"),
                },
                entity_ids=(binding.entity_id,),
                channel_bindings=(binding,),
            )
        )
        assert isinstance(outcome, DriverSuccess)

    enabled = driver.apply_state(
        DriverStatePatch(
            scoped_values=tuple(
                DriverStateEntry(
                    target=DC_SOURCE_OUTPUT_ENABLED,
                    value=True,
                    entity_ids=(binding.entity_id,),
                    channel_bindings=(binding,),
                )
                for binding in bindings
            )
        )
    )

    assert isinstance(enabled, DriverSuccess)
    q0 = world.dc_source("flux-dac-a:flux.dac_a.ch1")
    q1 = world.dc_source("flux-dac-a:flux.dac_a.ch2")
    assert (q0.voltage_level_v, q1.voltage_level_v) == (-0.08, 0.06)
    assert q0.output_enabled and q1.output_enabled

    driver.abort()

    assert not q0.output_enabled
    assert not q1.output_enabled
