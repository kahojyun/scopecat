"""Quantum demo configuration, compiler, and experiment-system composition."""

from __future__ import annotations

from pathlib import Path

from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum.pulse_recipes import PulseRecipeProfile

from quantum_lab_demo.compiler import QuantumLabCompiler
from quantum_lab_demo.configuration import (
    DEMO_VIRTUAL_LAB_PROFILE,
    quantum_lab_bootstrap_config,
)
from quantum_lab_demo.response_registry import QuantumLabResponseRegistry
from quantum_lab_demo.targets.configuration import (
    FAKE_LIST_TARGET_KIND,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListTarget,
    configured_fake_list_target,
)
from quantum_lab_demo.virtual_lab.compiler_parameters import QuantumCompilerParameters
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.virtual_lab.pulse_profile import QUANTUM_PULSE_PROFILE
from quantum_lab_demo.virtual_lab.quantum_responses import (
    quantum_lab_response_registry,
)

PathInput = str | Path


def quantum_lab_compiler(
    *,
    config_profile: ConfigProfileSnapshot | None = None,
    target: FakeListTarget | None = None,
    runtime: FakeListDomainRuntime | None = None,
    response_registry: QuantumLabResponseRegistry | None = None,
    pulse_profile: PulseRecipeProfile[QuantumCompilerParameters] | None = None,
) -> QuantumLabCompiler:
    """Compose list-mode compilation from one accepted configuration."""

    config = _config_snapshot(config_profile)
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
        pulse_profile=(
            QUANTUM_PULSE_PROFILE if pulse_profile is None else pulse_profile
        ),
    )


def quantum_lab_config_profile(
    config_profile: ConfigProfileSnapshot | None = None,
) -> ConfigProfileSnapshot:
    """Resolve the demo's explicit configuration snapshot."""

    return _config_snapshot(config_profile)


def quantum_lab_system(
    *,
    config: ConfigProfileSnapshot,
    virtual_lab_profile: PathInput = DEMO_VIRTUAL_LAB_PROFILE,
    compiler: QuantumLabCompiler | None = None,
) -> ExperimentSystem:
    """Compose one process-local system for notebook execution.

    Keeping domain dispatch at this single boundary gives every example the
    same routing, resource model, and target pipeline while each operation
    still specializes its own accepted parameter snapshot.
    """

    provider = QuantumLabVirtualProvider(profile=virtual_lab_profile)
    selected_compiler = (
        quantum_lab_compiler(config_profile=config) if compiler is None else compiler
    )
    _validate_target_selection(
        config,
        target_id=selected_compiler.target_id,
        target_kind=selected_compiler.target_kind,
    )
    return ExperimentSystem(
        provider=provider,
        domain_compiler=selected_compiler,
    )


def _config_snapshot(
    config_profile: ConfigProfileSnapshot | None,
) -> ConfigProfileSnapshot:
    if config_profile is None:
        return quantum_lab_bootstrap_config()
    return config_profile


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
    "PathInput",
    "quantum_lab_compiler",
    "quantum_lab_config_profile",
    "quantum_lab_system",
]
