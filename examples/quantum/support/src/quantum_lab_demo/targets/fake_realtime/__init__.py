"""Fake realtime target composition entry points."""

from quantum_lab_demo.targets.fake_realtime.compiler import FakeRealtimeCompiler
from quantum_lab_demo.targets.fake_realtime.defaults import (
    configured_fake_realtime_target,
)
from quantum_lab_demo.targets.fake_realtime.domain_runtime import (
    FakeRealtimeDomainRuntime,
)
from quantum_lab_demo.targets.fake_realtime.runtime import FakeRealtimeRuntime

__all__ = [
    "FakeRealtimeCompiler",
    "FakeRealtimeDomainRuntime",
    "FakeRealtimeRuntime",
    "configured_fake_realtime_target",
]
