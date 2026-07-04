from __future__ import annotations

from pathlib import Path

from scopecat.config_profiles import load_config_profile
from scopecat.experiments import ExperimentSpec, set_state
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.data_artifact import (
    DataArrayArtifact,
    DataArrayDimension,
    DataArraySchema,
    DataArrayVariable,
    DataColumn,
    DataTableArtifact,
    DataTableSchema,
)
from scopecat.relations import param
from scopecat.runs import artifact_storage_ref, dataset_storage_ref, open_run_store
from tests.support.records import read_model

WORKFLOW_FIXTURE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(WORKFLOW_FIXTURE_DIR / "config-profile.json")


def load_experiment() -> ExperimentSpec:
    return read_model(WORKFLOW_FIXTURE_DIR / "experiment.json", ExperimentSpec)


def config_with_instrument_id(instrument_id: str) -> ConfigProfileSnapshot:
    config = load_config()
    instrument = config.instrument_registry.instruments[0].model_copy(
        update={"id": instrument_id}
    )
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={"instruments": [instrument]}
            )
        }
    )
    connection = config.connection_profile.connections[0].model_copy(
        update={
            "id": f"{instrument_id}-connection",
            "instrument_id": instrument_id,
        }
    )
    environment = config.environment.model_copy(
        update={
            "connection_profile": config.connection_profile.model_copy(
                update={"connections": [connection]}
            )
        }
    )
    return config.model_copy(update={"system": system, "environment": environment})


def experiment_with_resource_id(resource_id: str) -> ExperimentSpec:
    experiment = load_experiment()
    return experiment.model_copy(
        update={
            "state": [
                set_state(
                    resource_id,
                    "set_frequency.frequency",
                    param("drive_frequency"),
                )
            ]
        }
    )


def attach_typed_data_artifacts(workspace: Path, run_id: str) -> None:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    metrics_schema = DataTableSchema(
        columns=[
            DataColumn(id="metric", role="identifier", dtype="string"),
            DataColumn(id="value", role="observable", dtype="float64", unit="ratio"),
        ],
        primary_key=["metric"],
    )
    matrix_schema = DataArraySchema(
        dimensions=[
            DataArrayDimension(id="prepared_state", kind="state", size=2),
            DataArrayDimension(id="assigned_state", kind="state", size=2),
        ],
        variables=[
            DataArrayVariable(
                id="readout_probability",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["prepared_state", "assigned_state"],
                shape=[2, 2],
            )
        ],
        primary_variables=["readout_probability"],
    )
    metrics_entry = RunDatasetEntry(
        id="metrics",
        kind="data_table",
        media_type="application/json",
        role="analysis",
        schema=metrics_schema.model_dump(mode="json"),
        metadata={"data_shape": "table"},
    )
    matrix_entry = RunDatasetEntry(
        id="readout-matrix",
        kind="data_array",
        media_type="application/json",
        role="analysis",
        schema=matrix_schema.model_dump(mode="json"),
        metadata={"data_shape": "array"},
    )
    metrics_ref = dataset_storage_ref(metrics_entry)
    matrix_ref = dataset_storage_ref(matrix_entry)
    storage.ref_path(run_id, metrics_ref).parent.mkdir(parents=True, exist_ok=True)
    storage.ref_path(run_id, metrics_ref).write_text(
        DataTableArtifact(
            schema=metrics_schema,
            rows=[{"metric": "visibility", "value": 0.98}],
        ).model_dump_json(by_alias=True)
    )
    storage.ref_path(run_id, matrix_ref).parent.mkdir(parents=True, exist_ok=True)
    storage.ref_path(run_id, matrix_ref).write_text(
        DataArrayArtifact(
            schema=matrix_schema,
            variables={"readout_probability": [[0.99, 0.03], [0.01, 0.97]]},
        ).model_dump_json(by_alias=True)
    )
    manifest.datasets.extend([metrics_entry, matrix_entry])
    storage.write_manifest(manifest)


def attach_binary_artifact(workspace: Path, run_id: str) -> None:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    binary = RunArtifactEntry(
        id="binary-artifact",
        kind="binary",
        media_type="application/octet-stream",
    )
    binary_ref = artifact_storage_ref(binary)
    binary_path = storage.ref_path(run_id, binary_ref)
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_bytes(b"\x00\x01")
    manifest.artifacts.append(binary)
    storage.write_manifest(manifest)
