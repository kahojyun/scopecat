from __future__ import annotations

import pytest
from scopecat.authoring import ExperimentInvocation
from scopecat.execution.points import RunPoint
from scopecat.measurements.projection import MeasurementProjection
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.config import ConfigProfileSnapshot

from quantum_lab_demo.workflows.fixed_patch_readout import (
    FIXED_PATCH_READOUT_TEMPLATE_ID,
    fixed_patch_readout_template,
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
    load_experiment_config,
    measurement_projection_and_points,
)


def test_recommended_workflow_template_ids() -> None:
    assert [
        readout_frequency_template.id,
        single_qubit_rb_template.id,
        fixed_patch_readout_template.id,
        qnd_repeated_measurement_template.id,
    ] == [
        READOUT_TEMPLATE_ID,
        SINGLE_QUBIT_RB_TEMPLATE_ID,
        FIXED_PATCH_READOUT_TEMPLATE_ID,
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
            fixed_patch_readout_template.bind(rounds=2),
            FIXED_PATCH_READOUT_TEMPLATE_ID,
            "fixed_patch_readout",
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
    resolved = resolve_experiment(invocation, config_profile=config)
    projection, points = _measurement_projection(invocation, config)

    assert resolved.template_id == template_id
    assert resolved.experiment.kind == kind
    assert projection.schema_for(points) is not None


def test_fixed_patch_readout_uses_recursive_result_axes() -> None:
    projection, points = _measurement_projection(
        fixed_patch_readout_template.bind(rounds=2, shots=3)
    )
    observable = next(
        record for record in projection.records if record.id == "patch_iq"
    )

    assert observable.dims == ("point", "shot", "round", "qubit")
    assert (len(points), *observable.shape[1:]) == (1, 3, 2, 4)


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
