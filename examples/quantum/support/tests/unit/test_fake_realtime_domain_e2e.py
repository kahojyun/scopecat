from pathlib import Path
from typing import Annotated, cast

import scopecat as sc
from scopecat.measurements.results import MeasurementArray
from scopecat_quantum import authoring as q

from quantum_lab_demo import quantum_realtime_lab_compiler
from quantum_lab_demo.targets.fake_realtime import (
    RtDecrementAndJump,
    RtJumpIf,
    RtPulseTimeline,
)
from quantum_lab_demo.virtual_lab.parameters import qubit_parameters
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

from .demo_lab_experiment_testkit import embedded_quantum_lab


@q.program(id="domain-detector-history")
def _detector_history_program(
    qubit: q.Qubit,
    rounds: Annotated[int, sc.IntType(minimum=1)],
) -> q.QuantumFragment:
    previous_state = q.bit_state("previous", initial=0)
    previous = q.read_bit(previous_state, id="previous")
    measurement = q.measure(qubit, result="syndrome_iq", bit="current")
    detector = q.xor_bits(measurement.bit, previous.bit, id="detector")
    return q.sequence(
        previous_state,
        q.repeat(
            q.sequence(
                previous,
                measurement,
                detector,
                q.emit_bit(detector.bit, result="detector"),
                q.store_bit(previous_state, measurement.bit),
            ),
            rounds,
            axis="round",
        ),
    )


@sc.scratch(id="test.domain-detector-history", kind="detector_history")
def _detector_history_experiment() -> sc.ExperimentBody:
    call = (
        _detector_history_program(qubit="q0", rounds=3)
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(2)
    )
    return sc.experiment(call).record_product(call.results.detector)


def test_active_reset_runs_through_the_domain_compiler_without_unrolling(
    tmp_path: Path,
) -> None:
    config = quantum_wiring_config_profile(target="fake-realtime")
    compiler = quantum_realtime_lab_compiler(
        config_profile=config, measurement_bits={"reset_iq": (0, 1, 0, 1, 1, 0)}
    )
    lab = embedded_quantum_lab(
        workspace=tmp_path,
        config_profile=config,
        compiler=compiler,
    )

    run = lab.prepare(active_reset_template.bind(rounds=3, shots=2)).run()

    assert run.manifest.status == "completed"
    assert compiler.trace.physical_execution_count == 1
    [evidence] = compiler.trace.realtime_preparations
    assert evidence.program_id == active_reset_program.id
    instructions = evidence.artifact.program.instructions
    assert sum(isinstance(item, RtDecrementAndJump) for item in instructions) == 1
    assert sum(isinstance(item, RtJumpIf) for item in instructions) == 1
    timelines = tuple(
        item for item in instructions if isinstance(item, RtPulseTimeline)
    )
    assert len(timelines) == 2
    assert sum(bool(item.acquisitions) for item in timelines) == 1
    assert sum(bool(item.plays) and not item.acquisitions for item in timelines) == 1
    [layout] = evidence.request.result_layouts
    assert [(axis.id, axis.size) for axis in layout.axes] == [("round", 3)]


def test_direct_interaction_layout_runs_on_the_realtime_target(
    tmp_path: Path,
) -> None:
    config = quantum_wiring_config_profile(target="fake-realtime")
    compiler = quantum_realtime_lab_compiler(config_profile=config)
    lab = embedded_quantum_lab(
        workspace=tmp_path,
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
    [evidence] = compiler.trace.realtime_preparations
    assert evidence.program_id == interaction_tomography_program.id
    instructions = evidence.artifact.program.instructions
    timelines = tuple(
        item for item in instructions if isinstance(item, RtPulseTimeline)
    )
    assert len(timelines) == 2
    direct = next(item for item in timelines if not item.acquisitions)
    measurement = next(item for item in timelines if item.acquisitions)
    assert direct.duration_ticks == 12
    assert sorted(item.start_ticks for item in direct.plays) == [0, 2, 3]
    assert sorted(item.duration_ticks for item in direct.plays) == [6, 8, 12]
    assert measurement.duration_ticks == 2
    assert len(measurement.plays) == 2
    assert len(measurement.acquisitions) == 2
    assert {layout.slot_id.local_id for layout in evidence.request.result_layouts} == {
        "control_iq_shots",
        "target_iq_shots",
    }
    assert all(not layout.axes for layout in evidence.request.result_layouts)


def test_emitted_detector_is_a_typed_domain_result_with_ssa_provenance(
    tmp_path: Path,
) -> None:
    config = quantum_wiring_config_profile(target="fake-realtime")
    compiler = quantum_realtime_lab_compiler(
        config_profile=config, measurement_bits={"syndrome_iq": (0, 1, 0, 1, 1, 0)}
    )
    run = (
        embedded_quantum_lab(
            workspace=tmp_path,
            config_profile=config,
            compiler=compiler,
        )
        .prepare(_detector_history_experiment())
        .run()
    )

    [record] = run.data().measurements().dataset.records
    detector = cast("MeasurementArray", record.observables["detector"])
    [evidence] = compiler.trace.realtime_preparations
    [origin] = evidence.request.realtime_result_provenance

    assert detector.dtype == "int64"
    assert detector.unit == "count"
    assert detector.shape == [2, 3]
    assert detector.values == [[0, 1, 1], [1, 0, 1]]
    assert origin.result_id.local_id == "detector"
    assert origin.source_value_id.local_id == "detector"
