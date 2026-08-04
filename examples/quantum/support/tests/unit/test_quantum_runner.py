from __future__ import annotations

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation

from quantum_lab_demo.quantum_runner import run_quantum
from quantum_lab_demo.workflows.drag_beta_calibration import drag_beta_program
from quantum_lab_demo.workflows.drag_beta_experiment import drag_beta_experiment


def test_lab_runner_accepts_a_program_call_without_a_wrapper_module() -> None:
    call = drag_beta_program(
        qubit="q0",
        amplification=2,
        beta=sc.Quantity(0.5, "ns"),
    ).with_shots(7)

    invocation = run_quantum(call)
    logical = compile_invocation(invocation).program.program

    assert invocation.definition.body.child_instances == ()
    [execution] = logical.domain_executions
    assert execution.id == ("drag-beta-rough-calibration/drag-beta-rough-calibration")
    assert [name for name, _value_id in execution.compiler_inputs] == ["qubits"]
    assert [record.record_id for record in logical.product_record_selections] == [
        "capture/probability_0",
        "capture/probability_1",
    ]
    assert [
        postprocessor.id.qualified_name
        for postprocessor in logical.measurement_postprocessors
    ] == ["binary-iq-probability"]


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
