from __future__ import annotations

from pathlib import Path
from typing import assert_type

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqProbabilityProducts,
)
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.instrument_host import compose_test_instruments

from reference_lab.compiler import QuantumLabCompiler
from reference_lab.configuration import bootstrap_config
from reference_lab.payloads import reference_lab_payload_codecs
from reference_lab.provider import ReferenceLabProvider
from reference_lab.quantum_runner import quantum_capture, run_quantum
from reference_lab.targets.list_mode import configured_list_mode_target
from reference_lab.workflows.drag_beta_calibration import drag_beta_program
from reference_lab.workflows.drag_beta_experiment import drag_beta_experiment


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


def _logical_measurement_values(
    tmp_path: Path,
    config: ConfigProfileSnapshot,
) -> tuple[object, ...]:
    provider = ReferenceLabProvider(seed=7)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(target=_configured_target(config, provider)),
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
    assert [port.id for port in capture.module.definition.interface.imports] == [
        "__structural_0"
    ]
    [child] = invocation.definition.body.child_instances
    assert child.instance_id == "capture"
    [execution] = logical.domain_executions
    assert execution.id == (
        "capture/drag-beta-rough-calibration/drag-beta-rough-calibration"
    )
    assert [name for name, _value_id in execution.compiler_inputs] == ["qubits"]
    assert [record.record_id for record in logical.product_record_selections] == [
        "capture/probability_0",
        "capture/probability_1",
    ]
    assert [
        postprocessor.id.qualified_name
        for postprocessor in logical.measurement_postprocessors
    ] == ["capture/binary-iq-probability"]


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
        record.record_id for record in fixed.product_record_selections
    ]
    assert [
        postprocessor.id.qualified_name
        for postprocessor in direct.measurement_postprocessors
    ] == [
        postprocessor.id.qualified_name
        for postprocessor in fixed.measurement_postprocessors
    ]


def test_quantum_target_executes_through_reserved_bare_instruments(
    tmp_path: Path,
) -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(target=_configured_target(config, provider)),
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


def test_quantum_target_lowers_integrated_iq_to_digitizer_dsp(
    tmp_path: Path,
) -> None:
    config = _with_dsp_policy(bootstrap_config(), "device")
    provider = ReferenceLabProvider(seed=7)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(target=_configured_target(config, provider)),
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
