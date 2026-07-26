from __future__ import annotations

import pytest
from scopecat.authoring import ExperimentInvocation
from scopecat.measurements.points import RunPoint
from scopecat.measurements.projection import MeasurementProjection
from scopecat.records.config import ConfigProfileSnapshot

from quantum_lab_demo.workflows.interaction_tomography import (
    INTERACTION_TOMOGRAPHY_TEMPLATE_ID,
    interaction_tomography_template,
)
from quantum_lab_demo.workflows.qnd import (
    QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    qnd_repeated_measurement_template,
)
from quantum_lab_demo.workflows.readout_frequency import (
    READOUT_TEMPLATE_ID,
    readout_frequency_template,
)
from quantum_lab_demo.workflows.single_qubit_rb import (
    CLIFFORD_LENGTH,
    RB_SEED,
    SINGLE_QUBIT_RB_TEMPLATE_ID,
    single_qubit_rb_template,
)

from .demo_lab_experiment_testkit import (
    link_invocation,
    load_experiment_config,
    measurement_projection_and_points,
)


def test_recommended_workflow_template_ids() -> None:
    assert [
        readout_frequency_template.definition.id,
        single_qubit_rb_template.definition.id,
        interaction_tomography_template.definition.id,
        qnd_repeated_measurement_template.definition.id,
    ] == [
        READOUT_TEMPLATE_ID,
        SINGLE_QUBIT_RB_TEMPLATE_ID,
        INTERACTION_TOMOGRAPHY_TEMPLATE_ID,
        QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    ]


@pytest.mark.parametrize(
    ("invocation", "template_id", "kind"),
    [
        (
            readout_frequency_template.bind(qubit="q0"),
            READOUT_TEMPLATE_ID,
            "readout_frequency",
        ),
        (
            single_qubit_rb_template.bind()
            .scan(CLIFFORD_LENGTH, [4, 8])
            .scan(RB_SEED, [11]),
            SINGLE_QUBIT_RB_TEMPLATE_ID,
            "single_qubit_rb",
        ),
        (
            interaction_tomography_template.bind(shots=2),
            INTERACTION_TOMOGRAPHY_TEMPLATE_ID,
            "interaction-tomography",
        ),
        (
            qnd_repeated_measurement_template.bind(
                qubit="q0",
                rounds=3,
                shots=5,
            ),
            QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
            "qnd_repeated_measurement",
        ),
    ],
)
def test_workflow_template_resolves_and_projects(
    invocation: ExperimentInvocation,
    template_id: str,
    kind: str,
) -> None:
    config = load_experiment_config()
    resolved = link_invocation(invocation, config_profile=config)
    projection, points = _measurement_projection(invocation, config)

    assert resolved.program.id == template_id
    assert resolved.program.kind == kind
    assert projection.schema_for(points) is not None


def test_interaction_tomography_projects_the_compact_scan_matrix() -> None:
    projection, points = _measurement_projection(
        interaction_tomography_template.bind(shots=3)
    )
    observables = {
        record.id: record
        for record in projection.records
        if record.id in {"control_iq_shots", "target_iq_shots"}
    }

    assert len(points) == 24
    assert set(observables) == {"control_iq_shots", "target_iq_shots"}
    assert all(
        observable.dims == ("point", "shot") for observable in observables.values()
    )
    assert all(
        (len(points), *observable.shape[1:]) == (24, 3)
        for observable in observables.values()
    )


def test_qnd_repeated_measurement_keeps_dense_shot_round_array() -> None:
    projection, points = _measurement_projection(
        qnd_repeated_measurement_template.bind(
            qubit="q0",
            rounds=3,
            shots=5,
        )
    )
    observable = next(record for record in projection.records if record.id == "qnd_iq")

    assert len(points) == 1
    assert observable.dims == ("point", "shot", "round")
    assert (len(points), *observable.shape[1:]) == (1, 5, 3)


def _measurement_projection(
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot | None = None,
) -> tuple[MeasurementProjection, tuple[RunPoint, ...]]:
    return measurement_projection_and_points(invocation, config=config)
