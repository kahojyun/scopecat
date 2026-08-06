from __future__ import annotations

from scopecat.execution.local.program import ApplyStateOperation
from tests.testkit.authoring import bind_invocation
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)

from reference_lab.configuration import bootstrap_config
from reference_lab.workflows.multichannel_bias import multichannel_dc_bias


def test_bias_profiles_materialize_as_one_channel_batch_per_physical_device() -> None:
    plan = materialize_local_execution(
        bind_invocation(
            multichannel_dc_bias(),
            config_profile=bootstrap_config(),
        )
    )
    bias_batches = tuple(
        operation
        for operation in operations_of_type(plan, ApplyStateOperation, point_index=0)
        if any(
            target.interface_id == "scopecat.dc_bias/v1" for target in operation.targets
        )
    )

    assert len(bias_batches) == 6
    assert [operation.instrument_id for operation in bias_batches] == [
        "flux-dac-a",
        "flux-dac-b",
        "flux-dac-a",
        "flux-dac-b",
        "flux-dac-a",
        "flux-dac-b",
    ]
    for operation in bias_batches:
        assert len(operation.targets) == 6
        assert {
            binding.channel_id
            for target in operation.targets
            for binding in target.channel_bindings
        } == (
            {"flux.dac_a.ch1", "flux.dac_a.ch2"}
            if operation.instrument_id == "flux-dac-a"
            else {"flux.dac_b.ch1", "flux.dac_b.ch2"}
        )
