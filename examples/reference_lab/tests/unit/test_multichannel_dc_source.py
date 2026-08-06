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
    DC_BIAS_RAMP_DURATION,
    DC_BIAS_SETTLE_TOLERANCE,
    DC_BIAS_TARGET_VOLTAGE,
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


def _bias_binding(entity_id: str, channel_id: str) -> CommandChannelBinding:
    return CommandChannelBinding(
        entity_id=entity_id,
        channel_id=channel_id,
        interface_id="scopecat.dc_bias/v1",
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


def test_vector_bias_patch_reports_each_settled_channel() -> None:
    world = VirtualLabWorld(seed=5)
    driver = MultiChannelVirtualDcSource("flux-dac-a", world)
    bindings = (
        _bias_binding("q0", "flux.dac_a.ch1"),
        _bias_binding("q1", "flux.dac_a.ch2"),
    )
    levels = (-0.08, 0.06)

    outcome = driver.apply_state(
        DriverStatePatch(
            scoped_values=tuple(
                entry
                for binding, level in zip(bindings, levels, strict=True)
                for entry in (
                    DriverStateEntry(
                        target=DC_BIAS_TARGET_VOLTAGE,
                        value=Quantity(level, "V"),
                        entity_ids=(binding.entity_id,),
                        channel_bindings=(binding,),
                    ),
                    DriverStateEntry(
                        target=DC_BIAS_RAMP_DURATION,
                        value=Quantity(0.25, "s"),
                        entity_ids=(binding.entity_id,),
                        channel_bindings=(binding,),
                    ),
                    DriverStateEntry(
                        target=DC_BIAS_SETTLE_TOLERANCE,
                        value=Quantity(0.1, "mV"),
                        entity_ids=(binding.entity_id,),
                        channel_bindings=(binding,),
                    ),
                )
            )
        )
    )

    assert isinstance(outcome, DriverSuccess)
    assert outcome.metadata == {
        "channel_results": {
            "flux.dac_a.ch1": {
                "status": "settled",
                "actual_voltage_v": -0.08,
            },
            "flux.dac_a.ch2": {
                "status": "settled",
                "actual_voltage_v": 0.06,
            },
        }
    }
    assert world.dc_source("flux-dac-a:flux.dac_a.ch1").voltage_level_v == -0.08
    assert world.dc_source("flux-dac-a:flux.dac_a.ch2").voltage_level_v == 0.06
