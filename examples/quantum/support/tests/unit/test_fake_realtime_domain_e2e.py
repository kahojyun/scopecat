from pathlib import Path

import pytest
import scopecat as sc
from scopecat.sdk.domain import DomainCompilation, DomainCompileRequest
from scopecat_quantum.programs import (
    StructuredPulseBlock,
    StructuredPulseConditional,
    StructuredPulseNode,
    StructuredPulseParallel,
    StructuredPulseRepeat,
    StructuredPulseSequence,
)
from scopecat_quantum.pulses import Acquire, Play, schedule

from quantum_lab_demo import quantum_realtime_lab_compiler
from quantum_lab_demo.compiler import (
    QuantumRealtimeLabCompiler,
    _RealtimeQuantumLabArtifact,
)
from quantum_lab_demo.targets.fake_realtime.compiler import (
    pulse_region,
)
from quantum_lab_demo.targets.fake_realtime.defaults import (
    configured_fake_realtime_target,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile
from quantum_lab_demo.workflows.active_reset import (
    active_reset_program,
    active_reset_template,
)
from quantum_lab_demo.workflows.interaction_tomography import (
    ANALYSIS_BASIS,
    INTERACTION_AMPLITUDE,
    PREPARATION,
    interaction_tomography_program,
    interaction_tomography_template,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab


def _pulse_regions(
    node: StructuredPulseNode,
) -> tuple[StructuredPulseBlock | StructuredPulseParallel, ...]:
    if isinstance(node, StructuredPulseBlock | StructuredPulseParallel):
        return (node,)
    if isinstance(node, StructuredPulseSequence):
        children = node.operations
    elif isinstance(node, StructuredPulseRepeat):
        children = (node.operation,)
    else:
        assert isinstance(node, StructuredPulseConditional)
        children = (node.when_true, node.when_false)
    return tuple(region for child in children for region in _pulse_regions(child))


def test_active_reset_runs_through_the_domain_compiler_without_unrolling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = quantum_wiring_config_profile(target="fake-realtime")
    compiler = quantum_realtime_lab_compiler(
        config_profile=config, measurement_bits={"reset_iq": (0, 1, 0, 1, 1, 0)}
    )
    compilations = _capture_compilations(compiler, monkeypatch)
    lab = in_process_quantum_lab(
        project_root=tmp_path,
        config_profile=config,
        compiler=compiler,
    )

    run = lab.prepare(active_reset_template.bind(rounds=3, shots=2)).run()

    assert run.manifest.status == "completed"
    [compilation] = compilations
    artifact = _realtime_artifact(compilation)
    assert artifact.program.id == active_reset_program.id
    assert isinstance(artifact.compiled.artifact.program.body, StructuredPulseRepeat)
    repeated = artifact.compiled.artifact.program.body.operation
    assert isinstance(repeated, StructuredPulseSequence)
    assert (
        sum(
            isinstance(item, StructuredPulseConditional) for item in repeated.operations
        )
        == 1
    )
    assert len(_pulse_regions(repeated)) == 2
    [layout] = artifact.request.result_layouts
    assert [(axis.id, axis.size) for axis in layout.axes] == [("round", 3)]


def test_direct_interaction_layout_runs_on_the_realtime_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = quantum_wiring_config_profile(target="fake-realtime")
    target = configured_fake_realtime_target(config)
    compiler = quantum_realtime_lab_compiler(config_profile=config, target=target)
    compilations = _capture_compilations(compiler, monkeypatch)
    lab = in_process_quantum_lab(
        project_root=tmp_path,
        config_profile=config,
        compiler=compiler,
    )

    run = (
        lab.prepare(interaction_tomography_template.bind(shots=2))
        .scan(PREPARATION, ("00",))
        .scan(ANALYSIS_BASIS, ("z",))
        .scan(INTERACTION_AMPLITUDE, (sc.Quantity(0.03, "arb"),))
        .run()
    )

    assert run.manifest.status == "completed"
    [compilation] = compilations
    artifact = _realtime_artifact(compilation)
    assert artifact.program.id == interaction_tomography_program.id
    regions = tuple(
        schedule(pulse_region(region)[0])
        for region in _pulse_regions(artifact.compiled.artifact.program.body)
    )
    assert len(regions) == 2
    direct = next(region for region in regions if not region.acquisition_slots)
    measurement = next(region for region in regions if region.acquisition_slots)
    clock_hz = target.clock_hz
    assert int(direct.duration_seconds * clock_hz) == 12
    plays = tuple(
        event for event in direct.events if isinstance(event.instruction, Play)
    )
    assert sorted(int(item.start_seconds * clock_hz) for item in plays) == [0, 2, 3]
    assert sorted(int(item.duration_seconds * clock_hz) for item in plays) == [6, 8, 12]
    assert int(measurement.duration_seconds * clock_hz) == 2
    assert sum(isinstance(event.instruction, Play) for event in measurement.events) == 2
    assert (
        sum(isinstance(event.instruction, Acquire) for event in measurement.events) == 2
    )
    assert {layout.slot_id.local_id for layout in artifact.request.result_layouts} == {
        "control_iq_shots",
        "target_iq_shots",
    }
    assert all(not layout.axes for layout in artifact.request.result_layouts)


def _capture_compilations(
    compiler: QuantumRealtimeLabCompiler,
    monkeypatch: pytest.MonkeyPatch,
) -> list[DomainCompilation]:
    compilations: list[DomainCompilation] = []
    compile_domain = compiler.compile

    def compile_and_capture(request: DomainCompileRequest) -> DomainCompilation:
        compilation = compile_domain(request)
        compilations.append(compilation)
        return compilation

    monkeypatch.setattr(compiler, "compile", compile_and_capture)
    return compilations


def _realtime_artifact(
    compilation: DomainCompilation,
) -> _RealtimeQuantumLabArtifact:
    [job] = compilation.jobs
    artifact = job.artifact
    assert isinstance(artifact, _RealtimeQuantumLabArtifact)
    return artifact
