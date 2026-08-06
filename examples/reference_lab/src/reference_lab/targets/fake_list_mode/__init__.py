"""Fake list-mode AWG and segmented-digitizer target."""

from reference_lab.targets.fake_list_mode.circuit_runtime import (
    CorrelatedFakeListRun,
    correlate_fake_list_run,
    realize_fake_measurements,
)
from reference_lab.targets.fake_list_mode.compiler import FakeListTargetCompiler
from reference_lab.targets.fake_list_mode.defaults import (
    configured_fake_list_target,
)
from reference_lab.targets.fake_list_mode.domain_runtime import (
    FakeListDomainRuntime,
    FakeMeasurementInvocationSpec,
    MappedFakeListTarget,
    fake_measurement_invocation_spec,
    realize_fetched_fake_measurements,
)
from reference_lab.targets.fake_list_mode.model import (
    FakeAcquisitionBinding,
    FakeAcquisitionWindow,
    FakeAwgChannelId,
    FakeChannelWaveform,
    FakeDigitizerChannelId,
    FakeListArtifact,
    FakeListEntry,
    FakeListTarget,
    FakeOutputBinding,
    FakeOutputSignal,
)
from reference_lab.targets.fake_list_mode.runtime import (
    DeterministicFakeAcquisitionResponse,
    FakeAcquisitionResponse,
    FakeAwgPlayback,
    FakeDigitizerFrame,
    FakeDigitizerValue,
    FakeListRun,
    FakeListRuntime,
)

__all__ = [
    "CorrelatedFakeListRun",
    "DeterministicFakeAcquisitionResponse",
    "FakeAcquisitionBinding",
    "FakeAcquisitionResponse",
    "FakeAcquisitionWindow",
    "FakeAwgChannelId",
    "FakeAwgPlayback",
    "FakeChannelWaveform",
    "FakeDigitizerChannelId",
    "FakeDigitizerFrame",
    "FakeDigitizerValue",
    "FakeListArtifact",
    "FakeListDomainRuntime",
    "FakeListEntry",
    "FakeListRun",
    "FakeListRuntime",
    "FakeListTarget",
    "FakeListTargetCompiler",
    "FakeMeasurementInvocationSpec",
    "FakeOutputBinding",
    "FakeOutputSignal",
    "MappedFakeListTarget",
    "configured_fake_list_target",
    "correlate_fake_list_run",
    "fake_measurement_invocation_spec",
    "realize_fake_measurements",
    "realize_fetched_fake_measurements",
]
