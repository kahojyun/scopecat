"""Quantum demo configuration, compiler, and experiment-system composition."""

from __future__ import annotations

from pathlib import Path

from scopecat.config.profiles import load_config_profile
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum import PulseRecipeProfile

from quantum_lab_demo.compiler import QuantumLabCompiler, QuantumRealtimeLabCompiler
from quantum_lab_demo.configuration import DEMO_VIRTUAL_LAB_PROFILE
from quantum_lab_demo.response_registry import QuantumLabResponseRegistry
from quantum_lab_demo.targets.configuration import (
    FAKE_LIST_TARGET_KIND,
    FAKE_REALTIME_TARGET_KIND,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListTarget,
    configured_fake_list_target,
)
from quantum_lab_demo.targets.fake_realtime import (
    FakeRealtimeDomainRuntime,
    FakeRealtimeRuntime,
    FakeRealtimeTarget,
    configured_fake_realtime_target,
)
from quantum_lab_demo.trace import QuantumLabTrace
from quantum_lab_demo.virtual_lab.compiler_parameters import QuantumCompilerParameters
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.virtual_lab.pulse_profile import QUANTUM_PULSE_PROFILE
from quantum_lab_demo.virtual_lab.quantum_responses import (
    quantum_lab_response_registry,
)
from quantum_lab_demo.virtual_lab.wiring import (
    QuantumDemoTarget,
    quantum_wiring_config_profile,
)

PathInput = str | Path
ConfigProfileInput = PathInput | ConfigProfileSnapshot


def quantum_lab_compiler(
    *,
    config_profile: ConfigProfileInput | None = None,
    target: FakeListTarget | None = None,
    runtime: FakeListDomainRuntime | None = None,
    response_registry: QuantumLabResponseRegistry | None = None,
    trace: QuantumLabTrace | None = None,
    pulse_profile: PulseRecipeProfile[QuantumCompilerParameters] | None = None,
) -> QuantumLabCompiler:
    """Compose list-mode compilation from one accepted configuration."""

    config = _config_snapshot(config_profile, default_target="fake-list")
    selected_target = configured_fake_list_target(config) if target is None else target
    _validate_target_selection(
        config,
        target_id=selected_target.id.value,
        target_kind=FAKE_LIST_TARGET_KIND,
    )

    return QuantumLabCompiler(
        target=selected_target,
        runtime=FakeListDomainRuntime() if runtime is None else runtime,
        response_registry=(
            quantum_lab_response_registry()
            if response_registry is None
            else response_registry
        ),
        trace=QuantumLabTrace() if trace is None else trace,
        pulse_profile=(
            QUANTUM_PULSE_PROFILE if pulse_profile is None else pulse_profile
        ),
    )


def quantum_realtime_lab_compiler(
    *,
    config_profile: ConfigProfileInput | None = None,
    target: FakeRealtimeTarget | None = None,
    runtime: FakeRealtimeDomainRuntime | None = None,
    trace: QuantumLabTrace | None = None,
    pulse_profile: PulseRecipeProfile[QuantumCompilerParameters] | None = None,
    measurement_bits: dict[str, tuple[int, ...]] | None = None,
) -> QuantumRealtimeLabCompiler:
    """Compose realtime compilation from one accepted configuration."""

    config = _config_snapshot(config_profile, default_target="fake-realtime")
    selected_target = (
        configured_fake_realtime_target(config) if target is None else target
    )
    _validate_target_selection(
        config,
        target_id=selected_target.id.value,
        target_kind=FAKE_REALTIME_TARGET_KIND,
    )
    return QuantumRealtimeLabCompiler(
        target=selected_target,
        runtime=(
            FakeRealtimeDomainRuntime(FakeRealtimeRuntime(selected_target))
            if runtime is None
            else runtime
        ),
        trace=QuantumLabTrace() if trace is None else trace,
        pulse_profile=(
            QUANTUM_PULSE_PROFILE if pulse_profile is None else pulse_profile
        ),
        measurement_bits=measurement_bits,
    )


def quantum_lab_config_profile(
    config_profile: ConfigProfileInput | None = None,
) -> ConfigProfileSnapshot:
    """Resolve the demo's explicit configuration snapshot."""

    return _config_snapshot(config_profile, default_target="fake-list")


def quantum_lab_system(
    *,
    config: ConfigProfileSnapshot,
    virtual_lab_profile: PathInput = DEMO_VIRTUAL_LAB_PROFILE,
    compiler: QuantumLabCompiler | QuantumRealtimeLabCompiler | None = None,
) -> ExperimentSystem:
    """Compose one process-local system for daemon or delegated execution.

    Keeping domain dispatch at this single boundary gives every example the
    same routing, resource model, and target pipeline while each operation
    still specializes its own accepted parameter snapshot.
    """

    provider = QuantumLabVirtualProvider(profile=virtual_lab_profile)
    selected_compiler = _compiler_for_config(config) if compiler is None else compiler
    _validate_target_selection(
        config,
        target_id=selected_compiler.target_id,
        target_kind=selected_compiler.target_kind,
    )
    return ExperimentSystem(
        provider=provider,
        domain_compiler=selected_compiler,
    )


def _compiler_for_config(
    config: ConfigProfileSnapshot,
) -> QuantumLabCompiler | QuantumRealtimeLabCompiler:
    target = config.domain_target
    if target is None:
        raise ValueError("quantum demo configuration requires a domain target")
    if target.kind == FAKE_LIST_TARGET_KIND:
        return quantum_lab_compiler(config_profile=config)
    if target.kind == FAKE_REALTIME_TARGET_KIND:
        return quantum_realtime_lab_compiler(config_profile=config)
    raise ValueError(f"unsupported quantum demo target kind {target.kind!r}")


def _config_snapshot(
    config_profile: ConfigProfileInput | None,
    *,
    default_target: QuantumDemoTarget,
) -> ConfigProfileSnapshot:
    if config_profile is None:
        return quantum_wiring_config_profile(target=default_target)
    if isinstance(config_profile, ConfigProfileSnapshot):
        return config_profile
    return load_config_profile(config_profile)


def _validate_target_selection(
    config: ConfigProfileSnapshot,
    *,
    target_id: str,
    target_kind: str,
) -> None:
    target = config.domain_target
    if target is None:
        raise ValueError("quantum demo configuration requires a domain target")
    if (target.id, target.kind) != (target_id, target_kind):
        raise ValueError(
            "quantum compiler target must match the accepted configuration"
        )


__all__ = [
    "ConfigProfileInput",
    "PathInput",
    "quantum_lab_compiler",
    "quantum_lab_config_profile",
    "quantum_lab_system",
    "quantum_realtime_lab_compiler",
]
