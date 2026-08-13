from __future__ import annotations

from pathlib import Path
from typing import assert_type, cast

import pytest
import scopecat as sc
from scopecat.compiler.bind import bind_program
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.config.environment import build_config_environment
from scopecat.execution.evidence import instrument_state_evidence_ref
from scopecat.execution.local.program import ApplyStateOperation
from scopecat.execution.program import RunCoverageEffect, RunDomainJob
from scopecat.kernel.errors import CheckFailed
from scopecat.planning.compilation import compile_run_program
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution import InstrumentStateEvidence
from scopecat_quantum.measurement_computes import (
    BinaryIqProbabilityProducts,
)
from scopecat_testkit.instrument_host import compose_test_instruments
from scopecat_testkit.server.in_process_lab import in_process_lab

from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT,
    ANALOG_WAVEFORM_OUTPUT_RESET,
)
from reference_lab.compiler import QuantumLabCompiler
from reference_lab.configuration import bootstrap_config
from reference_lab.parameters import QUBITS
from reference_lab.payloads import reference_lab_payload_codecs
from reference_lab.provider import ReferenceLabProvider
from reference_lab.quantum_runner import (
    prepare_quantum_hardware,
    quantum_capture,
    run_quantum,
)
from reference_lab.targets.list_mode import (
    ListModeDomainRuntime,
    MappedListModeTarget,
    configured_list_mode_target,
)
from reference_lab.virtual_lab.execution import virtual_quantum_runtime
from reference_lab.workflows.drag_beta_calibration import drag_beta_program
from reference_lab.workflows.drag_beta_experiment import drag_beta_experiment
from reference_lab.workflows.ramsey_experiments import q0_fixed_if_lo_sweep


@sc.experiment
def _reset_guard_before_quantum(experiment: sc.ExperimentContext) -> None:
    prepare_quantum_hardware(experiment)
    guard = sc.capability_resource(
        experiment,
        "reset-iq-offset-guard",
        requires=(ANALOG_WAVEFORM_OUTPUT,),
        role="iq-offset-guard",
    )
    guard.invoke(ANALOG_WAVEFORM_OUTPUT_RESET)
    results = experiment.use(
        drag_beta_program(
            qubit="q0",
            amplification=2,
            beta=sc.Quantity(0.5, "ns"),
        )
        .with_shots(7)
        .with_compiler_inputs(qubits=QUBITS.ref)
    )
    experiment.alias(results.iq_shots)


def _configured_target(
    config: ConfigProfileSnapshot,
    provider: ReferenceLabProvider,
):
    catalog = resolve_instrument_contract_catalog(
        config=config,
        provider_id=provider.provider_id,
        describe=provider.describe,
    )
    return configured_list_mode_target(config, catalog)


def _with_dsp_policy(
    config: ConfigProfileSnapshot,
    policy: str,
) -> ConfigProfileSnapshot:
    target = config.domain_target
    assert target is not None
    configuration = target.configuration.copy()
    capabilities = configuration["capabilities"]
    assert isinstance(capabilities, dict)
    capabilities = capabilities.copy()
    capabilities["acquisition_dsp_policy"] = policy
    configuration["capabilities"] = capabilities
    return config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "domain_target": target.model_copy(
                        update={"configuration": configuration}
                    )
                }
            )
        }
    )


def _with_max_list_entries(
    config: ConfigProfileSnapshot,
    maximum: int,
) -> ConfigProfileSnapshot:
    target = config.domain_target
    assert target is not None
    configuration = target.configuration.copy()
    capabilities = configuration["capabilities"]
    assert isinstance(capabilities, dict)
    capabilities = capabilities.copy()
    capabilities["max_list_entries"] = maximum
    configuration["capabilities"] = capabilities
    return config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "domain_target": target.model_copy(
                        update={"configuration": configuration}
                    )
                }
            )
        }
    )


def test_quantum_compiler_uses_a_one_point_initial_probe() -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    compiler = QuantumLabCompiler(target=_configured_target(config, provider))

    assert compiler.initial_batch_size(1000) == 1


def _logical_measurement_values(
    tmp_path: Path,
    config: ConfigProfileSnapshot,
) -> tuple[object, ...]:
    provider = ReferenceLabProvider(seed=7)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(
            target=_configured_target(config, provider),
            runtime_selector=virtual_quantum_runtime,
        ),
        payload_codecs=reference_lab_payload_codecs(),
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )
    run = lab.prepare(drag_beta_experiment()).run()
    return tuple(
        (record.coordinates, record.observables)
        for record in run.measurements().records
    )


def test_lab_runner_places_the_reusable_capture_module() -> None:
    call = drag_beta_program(
        qubit="q0",
        amplification=2,
        beta=sc.Quantity(0.5, "ns"),
    ).with_shots(7)

    capture = assert_type(
        quantum_capture(call),
        sc.ModuleInvocation[BinaryIqProbabilityProducts],
    )
    invocation = run_quantum(call)
    logical = compile_invocation(invocation).program.program

    assert capture.instance_id == "capture"
    assert {
        port.selector.role.role_id
        for port in capture.module.definition.interface.resources
    } == {
        "drive-i",
        "drive-lo",
        "drive-q",
        "iq-offset-guard",
        "readout-i",
        "readout-lo",
        "readout-q",
    }
    [child] = invocation.definition.body.child_instances
    assert child.instance_id == "capture"
    [execution] = logical.domain_executions
    assert [name for name, _value_id in execution.compiler_inputs] == ["qubits"]
    assert [record.record_id for record in logical.product_record_selections] == [
        "probability_0",
        "probability_1",
    ]
    assert [compute.id.qualified_name for compute in logical.measurement_computes] == [
        "capture/binary-iq-probability"
    ]


def test_fixed_experiment_and_structural_runner_share_lab_measurement_policy() -> None:
    direct = compile_invocation(
        run_quantum(
            drag_beta_program(
                qubit="q0",
                amplification=2,
                beta=sc.Quantity(0.5, "ns"),
            ).with_shots(7)
        )
    ).program.program
    fixed = compile_invocation(drag_beta_experiment()).program.program

    assert [record.record_id for record in direct.product_record_selections] == [
        "probability_0",
        "probability_1",
    ]
    assert [record.record_id for record in fixed.product_record_selections] == [
        "probabilities/probability_0",
        "probabilities/probability_1",
    ]
    assert [compute.id.qualified_name for compute in direct.measurement_computes] == [
        compute.id.qualified_name for compute in fixed.measurement_computes
    ]


def test_quantum_target_executes_through_reserved_bare_instruments(
    tmp_path: Path,
) -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(
            target=_configured_target(config, provider),
            runtime_selector=virtual_quantum_runtime,
        ),
        payload_codecs=reference_lab_payload_codecs(),
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )

    run = lab.prepare(drag_beta_experiment()).run()

    assert run.manifest.status == "completed"
    assert len(run.measurements().records) == 15
    state_evidence = lab.services.runs.read_model(
        run.id,
        instrument_state_evidence_ref(),
        InstrumentStateEvidence,
    )
    drive_awg = next(
        state
        for state in state_evidence.final_state
        if state.instrument_id == "drive-awg"
    )
    guard_offset = next(
        state.value.root
        for state in drive_awg.properties
        if state.component_path == ["outputs", "ch9"] and state.property_id == "offset"
    )
    assert guard_offset == sc.Quantity(0.007, "V")


def test_quantum_preview_inspects_only_the_selected_point_without_device_effects(
    tmp_path: Path,
) -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(
            target=_configured_target(config, provider),
            runtime_selector=virtual_quantum_runtime,
        ),
        payload_codecs=reference_lab_payload_codecs(),
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )
    invocation = drag_beta_experiment()

    preview = lab.prepare(invocation).preview(point="last")

    assert lab.runs() == ()
    assert preview.selected_point is not None
    assert preview.selected_point.point_index == 14
    [inspection] = preview.domain_inspections
    assert inspection.point_indices == (14,)
    assert inspection.content["schema"] == (
        "reference_lab.list_mode_artifact_inspection.v1"
    )
    [entry] = cast("list[dict[str, object]]", inspection.content["entries"])
    assert cast("str", entry["entry_id"]).endswith(".point-14")

    selected_again = lab.prepare(invocation).preview(
        coordinates=preview.selected_point.coordinates
    )
    assert selected_again.selected_point == preview.selected_point

    bound = bind_program(
        compile_invocation(invocation).program,
        build_config_environment(config),
    )
    plan = compile_run_program(composition.system, bound=bound)
    actual_job = next(
        operation
        for operation in plan.coverage
        if isinstance(operation, RunDomainJob) and 14 in operation.point_ordinals
    )
    actual = cast(
        "MappedListModeTarget",
        actual_job.execution.invocation.payload,
    ).artifact
    actual_entry = next(
        item for item in actual.entries if item.entry_id.value.endswith("point-14")
    )
    preview_hashes = {
        waveform["channel_id"]: waveform["samples_sha256"]
        for waveform in cast("list[dict[str, str]]", entry["waveforms"])
    }
    actual_hashes = {
        waveform.channel_id.value: waveform.samples_sha256
        for waveform in actual_entry.waveforms
    }
    assert preview_hashes == actual_hashes


def test_target_and_device_dsp_follow_the_same_integrated_iq_semantics(
    tmp_path: Path,
) -> None:
    config = bootstrap_config()

    target_values = _logical_measurement_values(
        tmp_path / "target-dsp",
        _with_dsp_policy(config, "target"),
    )
    device_values = _logical_measurement_values(
        tmp_path / "device-dsp",
        _with_dsp_policy(config, "device"),
    )

    assert device_values == target_values


def test_quantum_scan_results_are_invariant_to_target_batch_boundaries(
    tmp_path: Path,
) -> None:
    config = bootstrap_config()

    one_entry_batches = _logical_measurement_values(
        tmp_path / "one-entry-batches",
        _with_max_list_entries(config, 1),
    )
    complete_batch = _logical_measurement_values(
        tmp_path / "complete-batch",
        config,
    )

    assert one_entry_batches == complete_batch


def test_reviewed_los_prepare_once_without_fragmenting_quantum_batches() -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    target = _configured_target(config, provider)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(target=target),
        payload_codecs=reference_lab_payload_codecs(),
    )
    bound = bind_program(
        compile_invocation(drag_beta_experiment()).program,
        build_config_environment(config),
    )

    plan = compile_run_program(composition.system, bound=bound)
    coverage = tuple(plan.coverage)

    state_effects = tuple(
        operation
        for covered in coverage
        if isinstance(covered, RunCoverageEffect)
        and isinstance(operation := covered.operation, ApplyStateOperation)
    )
    jobs = tuple(
        operation for operation in coverage if isinstance(operation, RunDomainJob)
    )
    assert all(type(job.execution.runtime) is ListModeDomainRuntime for job in jobs)
    assert [effect.instrument_id for effect in state_effects] == [
        "drive-awg",
        "readout-awg",
        "drive-lo-a",
        "drive-lo-b",
        "readout-lo",
    ]
    assert [job.point_ordinals for job in jobs] == [(0,), tuple(range(1, 15))]
    assert plan.domain_target_requirement is not None
    assert "drive-lo-a" not in plan.domain_target_requirement.instrument_ids
    assert "drive-lo-b" not in plan.domain_target_requirement.instrument_ids
    assert "readout-lo" not in plan.domain_target_requirement.instrument_ids
    assert {requirement.id for requirement in plan.resource_requirements} >= {
        "drive-lo-a",
        "drive-lo-b",
        "readout-lo",
    }
    host_addresses = {
        (
            effect.instrument_id,
            target.interface_id,
            target.component_path,
            target.property_id,
        )
        for effect in state_effects
        for target in effect.targets
        if effect.instrument_id in {"drive-awg", "readout-awg"}
    }
    domain_addresses = {
        (
            write.instrument_id,
            write.interface_id,
            write.component_path,
            write.property_id,
        )
        for job in jobs
        for write in job.execution.realtime_write_footprint
    }
    requirement_addresses = {
        (
            requirement.address.instrument_id,
            requirement.address.interface_id,
            requirement.address.component_path,
            requirement.address.property_id,
        )
        for job in jobs
        for requirement in job.execution.state_requirements
    }
    assert {address[0] for address in host_addresses} == {
        "drive-awg",
        "readout-awg",
    }
    assert {address[0] for address in domain_addresses} >= {
        "drive-awg",
        "readout-awg",
    }
    assert host_addresses.isdisjoint(domain_addresses)
    assert requirement_addresses == host_addresses
    assert all(job.execution.setup is not None for job in jobs)
    assert {
        (
            address.instrument_id,
            address.interface_id,
            address.component_path,
            address.property_id,
        )
        for job in jobs
        for address in job.execution.setup_state_invalidations
    } == requirement_addresses


def test_guard_reset_invalidates_state_required_by_quantum_domain() -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    target = _configured_target(config, provider)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(target=target),
        payload_codecs=reference_lab_payload_codecs(),
    )
    bound = bind_program(
        compile_invocation(_reset_guard_before_quantum()).program,
        build_config_environment(config),
    )

    plan = compile_run_program(composition.system, bound=bound)
    with pytest.raises(CheckFailed) as captured:
        tuple(plan.coverage)

    assert {problem.code for problem in captured.value.problems} == {
        "domain_state_requirement_missing"
    }
    assert captured.value.problems[0].details["state_address"] == (
        "drive-awg:reference_lab.analog_waveform_output/v1/outputs/ch9.offset"
    )
    assert captured.value.problems[0].details["invalidated_by"] == {
        "kind": "host_operation",
        "instrument_id": "drive-awg",
        "interface_id": "reference_lab.analog_waveform_output/v1",
        "component_path": ("outputs", "ch9"),
        "operation_id": "reset",
        "point_index": 0,
    }


def test_fixed_if_lo_sweep_bounds_real_time_batches_with_host_effects() -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    target = _configured_target(config, provider)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(target=target),
        payload_codecs=reference_lab_payload_codecs(),
    )
    bound = bind_program(
        compile_invocation(q0_fixed_if_lo_sweep()).program,
        build_config_environment(config),
    )

    plan = compile_run_program(composition.system, bound=bound)
    coverage = tuple(plan.coverage)

    state_effects = tuple(
        operation
        for covered in coverage
        if isinstance(covered, RunCoverageEffect)
        and isinstance(operation := covered.operation, ApplyStateOperation)
    )
    jobs = tuple(
        operation for operation in coverage if isinstance(operation, RunDomainJob)
    )
    assert {effect.instrument_id for effect in state_effects} == {
        "drive-awg",
        "drive-lo-a",
        "readout-awg",
        "readout-lo",
    }
    assert [job.point_ordinals for job in jobs] == [(0,), (1,), (2,)]
    assert plan.domain_target_requirement is not None
    assert plan.domain_target_requirement.instrument_ids == (
        "drive-awg",
        "readout-awg",
        "readout-digitizer",
        "timing-controller",
    )
    assert {requirement.id for requirement in plan.resource_requirements} == {
        "drive-awg",
        "drive-lo-a",
        "drive-lo-b",
        "readout-awg",
        "readout-digitizer",
        "readout-lo",
        "timing-controller",
    }
