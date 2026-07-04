from scopecat.experiments import (
    acquire,
    experiment,
    plan_experiment,
    point,
    set_state,
    trace,
    update_param_rows,
)
from scopecat.models.artifact import ExperimentAsset
from scopecat.models.parameter import Quantity
from scopecat.relations import (
    col,
    grid,
    linspace,
    param,
    table,
)
from tests.support.experiment_kernel import (
    hash_value as _hash,
)
from tests.support.experiment_kernel import (
    is_sha256 as _is_sha256,
)
from tests.support.experiment_kernel import (
    parameter_build as _parameter_build,
)
from tests.support.experiment_kernel import (
    payload_hash as _payload_hash,
)


def test_kernel_plans_points_patches_state_and_acquisition() -> None:
    spec = experiment(
        id="readout-frequency-calibration",
        kind="readout.frequency_scan",
        points=grid(
            readout=table("readout_devices").filter(col("enabled").eq(True)),
            readout_frequency=linspace(5.9, 6.0, 2, unit="GHz"),
        ),
        params=[
            update_param_rows(
                "readout_devices",
                key={"device_id": col("readout.device_id")},
                values={"frequency": col("readout_frequency")},
            )
        ],
        state=[
            set_state(
                col("readout.resource_id"),
                "pulse.frequency",
                param(
                    "readout_devices",
                    key={"device_id": col("readout.device_id")},
                    column="frequency",
                ),
            )
        ],
        acquire=acquire(
            "iq",
            shots=240,
            repetitions=1024,
            observations=[point("signal", unit="ratio")],
        ),
    )

    params = _parameter_build()
    plan = plan_experiment(spec, params)
    repeated = plan_experiment(spec, params)
    changed_metadata = plan_experiment(
        spec.model_copy(update={"metadata": {"operator": "alice"}}),
        params,
    )
    accepted_readout_table = params.table("readout_devices")

    assert spec.schema_version == "scopecat.experiment_spec.v1"
    assert plan.schema_version == "scopecat.plan_snapshot.v1"
    assert [point.point_id for point in plan.points] == [0, 1]
    assert plan.experiment_hash == _payload_hash(spec.model_dump(mode="json"))
    assert _is_sha256(plan.experiment_hash)
    assert changed_metadata.experiment_hash != plan.experiment_hash
    assert changed_metadata.content_hash != plan.content_hash
    assert plan.parameter_build_id == "build"
    assert plan.parameter_build_hash == params.content_hash
    assert plan.plan_implementation_id == "scopecat.planner.local"
    assert plan.plan_implementation_version == "v1"
    assert plan.point_coordinate_ids == ["readout_frequency"]
    assert _is_sha256(plan.content_hash)
    assert repeated.content_hash == plan.content_hash
    assert accepted_readout_table is not None
    assert accepted_readout_table.rows[0]["frequency"] == Quantity(
        value=5.95,
        unit="GHz",
    )
    assert [
        (record.patch.values or {})["frequency"] for record in plan.parameter_patches
    ] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
    assert [record.patch.table_id for record in plan.parameter_patches] == [
        "readout_devices",
        "readout_devices",
    ]
    assert [record.affected_rows for record in plan.parameter_patches] == [
        [
            {
                "device_id": "r0",
                "enabled": True,
                "resource_id": "readout-a",
                "frequency": Quantity(value=5.9, unit="GHz"),
            }
        ],
        [
            {
                "device_id": "r0",
                "enabled": True,
                "resource_id": "readout-a",
                "frequency": Quantity(value=6.0, unit="GHz"),
            }
        ],
    ]
    assert [record.value for record in plan.desired_state] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
    assert plan.acquisition.kind == "iq"
    assert plan.acquisition.estimated_records == 2
    assert [intent.model_dump(mode="json") for intent in plan.result_intents] == [
        {
            "id": "signal",
            "kind": "observable",
            "record": "point",
            "dimensions": [],
            "unit": "ratio",
            "resource": None,
            "estimated_records": 2,
            "metadata": {},
        }
    ]
    assert plan.expected_dataset_schema is not None
    assert plan.point_coordinate_ids == plan.expected_dataset_schema.primary_coordinates
    assert plan.expected_dataset_schema.dataset_id == (
        "readout-frequency-calibration.results"
    )
    assert plan.expected_dataset_schema.primary_coordinates == ["readout_frequency"]
    assert plan.expected_dataset_schema.primary_observables == ["signal"]
    assert [
        (variable.id, variable.role, variable.dtype, variable.unit, variable.shape)
        for variable in plan.expected_dataset_schema.variables
    ] == [
        ("readout_frequency", "coordinate", "float64", "GHz", [2]),
        ("signal", "observable", "float64", "ratio", [2]),
    ]


def test_kernel_plan_carries_parameter_build_diagnostics() -> None:
    params = _parameter_build().model_copy(
        update={
            "diagnostics": [
                {
                    "severity": "info",
                    "code": "derived_table_replaces_source",
                    "message": "derived table replaces a source table",
                    "path": "parameter_build.tables.readout_devices",
                }
            ]
        },
        deep=True,
    )
    spec = experiment(
        id="diagnostic-plan",
        kind="diagnostic",
        points=grid(frequency=linspace(5.9, 6.0, 1, unit="GHz")),
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, params)

    assert plan.diagnostics == params.diagnostics


def test_kernel_plan_carries_typed_artifacts() -> None:
    artifact = ExperimentAsset(
        id="compiled-waveforms",
        kind="waveform_bundle",
        content_hash=_hash("waveforms"),
        media_type="application/vnd.scopecat.waveforms+json",
    )
    spec = experiment(
        id="artifact-plan",
        kind="diagnostic",
        points=grid(index=[0]),
        acquire=acquire("iq"),
        assets=[artifact],
    )
    changed = spec.model_copy(
        update={
            "assets": [artifact.model_copy(update={"content_hash": _hash("changed")})]
        },
        deep=True,
    )

    plan = plan_experiment(spec, _parameter_build())
    changed_plan = plan_experiment(changed, _parameter_build())

    assert plan.assets == [artifact]
    assert changed_plan.content_hash != plan.content_hash


def test_kernel_result_intents_are_durable_and_hashed() -> None:
    spec = experiment(
        id="result-intent-plan",
        kind="diagnostic",
        points=grid(index=[0]),
        acquire=acquire(
            "iq",
            record="trace",
            dimensions=["time"],
            channels=["readout-a"],
            observations=[trace("iq_trace", unit="V", resource="readout-a")],
        ),
    )
    changed = spec.model_copy(
        update={
            "acquire": spec.acquire.model_copy(
                update={"observations": [trace("phase_trace")]}
            )
        },
        deep=True,
    )

    plan = plan_experiment(spec, _parameter_build())
    changed_plan = plan_experiment(changed, _parameter_build())
    payload = plan.model_dump(mode="json")

    assert payload["acquisition"]["channels"] == ["readout-a"]
    assert payload["acquisition"]["observations"][0]["id"] == "iq_trace"
    assert payload["result_intents"] == [
        {
            "id": "iq_trace",
            "kind": "artifact",
            "record": "trace",
            "dimensions": ["time"],
            "unit": "V",
            "resource": "readout-a",
            "estimated_records": 1,
            "metadata": {},
        }
    ]
    assert payload["expected_dataset_schema"] is None
    assert changed_plan.content_hash != plan.content_hash
