"""Workspace factories for the demo quantum lab workflows."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum import PulseRecipeProfile

from quantum_lab_demo.compiler import QuantumLabCompiler
from quantum_lab_demo.fixtures import (
    DEFAULT_EXPERIMENT_WORKSPACE,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
)
from quantum_lab_demo.response_registry import QuantumLabResponseRegistry
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListTarget,
    default_fake_list_target,
)
from quantum_lab_demo.trace import QuantumLabTrace
from quantum_lab_demo.virtual_lab.compiler_parameters import QuantumCompilerParameters
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.virtual_lab.pulse_profile import QUANTUM_PULSE_PROFILE
from quantum_lab_demo.virtual_lab.quantum_responses import (
    quantum_lab_response_registry,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile

PathInput = str | Path
ConfigProfileInput = PathInput | ConfigProfileSnapshot


def quantum_lab_compiler(
    *,
    target: FakeListTarget | None = None,
    runtime: FakeListDomainRuntime | None = None,
    response_registry: QuantumLabResponseRegistry | None = None,
    trace: QuantumLabTrace | None = None,
    pulse_profile: PulseRecipeProfile[QuantumCompilerParameters] | None = None,
) -> QuantumLabCompiler:
    """Compose the demo lab's one domain compiler from lab-owned policy."""

    return QuantumLabCompiler(
        target=default_fake_list_target() if target is None else target,
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


def quantum_lab(
    *,
    workspace: PathInput = DEFAULT_EXPERIMENT_WORKSPACE,
    config_profile: ConfigProfileInput | None = None,
    virtual_lab_profile: PathInput = EXPERIMENT_VIRTUAL_LAB_PROFILE,
    compiler: QuantumLabCompiler | None = None,
) -> sc.Workspace:
    """Open the demo environment with one compiler for all quantum Programs.

    Keeping domain dispatch at this single boundary gives every example the
    same routing, resource model, and target pipeline while each operation
    still specializes its own accepted parameter snapshot.
    """

    provider = QuantumLabVirtualProvider(profile=virtual_lab_profile)
    selected_compiler = quantum_lab_compiler() if compiler is None else compiler
    return sc.open(
        workspace,
        config_profile=config_profile or quantum_wiring_config_profile(),
        system=sc.ExperimentSystem(
            provider=provider,
            domain_compiler=selected_compiler,
        ),
    )


__all__ = [
    "ConfigProfileInput",
    "PathInput",
    "quantum_lab",
    "quantum_lab_compiler",
]
