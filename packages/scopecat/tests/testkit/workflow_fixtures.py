from __future__ import annotations

from pathlib import Path

from scopecat.authoring import (
    ExperimentInvocation,
    InputDescription,
    QuantityType,
    ScalarType,
    parameter,
    record_product,
)
from scopecat.authoring.scans import axis
from scopecat.compiler.frontend.invocation import (
    PreparedInvocation,
    prepare_invocation,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.config.profiles import load_config_profile
from scopecat.planning.authoring import resolve_experiment_with_config
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.data_artifact import (
    DataArrayArtifact,
    DataArrayDimension,
    DataArraySchema,
    DataArrayVariable,
    DataColumn,
    DataTableArtifact,
    DataTableSchema,
)
from scopecat.records.parameter import Quantity
from scopecat.runs.access import (
    artifact_storage_ref,
    dataset_storage_ref,
)
from scopecat.testing import sqlite_run_repository
from tests.testkit.authoring import (
    DRIVE_FREQUENCY_POINT,
    SIMPLE_MODULE,
    template_fixture,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as WORKFLOW_FIXTURE_DIR


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(WORKFLOW_FIXTURE_DIR / "config-profile.json")


def load_experiment() -> CoreProgram:
    """Compile the simple-scan DSL fixture into a transient typed program."""

    return resolve_experiment_with_config(
        load_invocation(),
        config=load_config(),
    ).experiment


def load_invocation() -> ExperimentInvocation:
    return template_fixture(
        SIMPLE_MODULE,
        id="test.workflow_scan",
        kind="simple_scan",
        inputs=(
            InputDescription(id="subject"),
            InputDescription(id="drive_frequency"),
        ),
        scans=(
            axis(
                DRIVE_FREQUENCY_POINT,
                center=parameter(
                    "drive_frequency",
                    ScalarType(QuantityType()),
                ),
                span=Quantity(value=200.0, unit="MHz"),
                points=3,
            ),
        ),
        records=(record_product(SIMPLE_MODULE.products.signal),),
    ).bind(subject="q0")


def load_prepared_invocation() -> PreparedInvocation:
    return prepare_invocation(load_invocation())


def config_with_instrument_id(instrument_id: str) -> ConfigProfileSnapshot:
    config = load_config()
    instrument = config.instrument_registry.instruments[0].model_copy(
        update={"id": instrument_id}
    )
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={"instruments": [instrument]}
            ),
            "routing": config.routing.model_copy(
                update={
                    "bindings": [
                        binding.model_copy(update={"instrument_id": instrument_id})
                        for binding in config.routing.bindings
                    ],
                }
            ),
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


def attach_typed_data_artifacts(project_root: Path, run_id: str) -> None:
    storage = sqlite_run_repository(project_root)
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
    metrics_entry = RunContentEntry(
        role="dataset",
        id="metrics",
        kind="data_table",
        content_hash="metrics-content",
        media_type="application/json",
        dataset_role="analysis",
        schema=metrics_schema.model_dump(mode="json"),
        metadata={"data_shape": "table"},
    )
    matrix_entry = RunContentEntry(
        role="dataset",
        id="readout-matrix",
        kind="data_array",
        content_hash="matrix-content",
        media_type="application/json",
        dataset_role="analysis",
        schema=matrix_schema.model_dump(mode="json"),
        metadata={"data_shape": "array"},
    )
    metrics_ref = dataset_storage_ref(metrics_entry)
    matrix_ref = dataset_storage_ref(matrix_entry)
    storage.write_text(
        run_id,
        metrics_ref,
        DataTableArtifact(
            schema=metrics_schema,
            rows=[{"metric": "visibility", "value": 0.98}],
        ).model_dump_json(by_alias=True),
    )
    storage.write_text(
        run_id,
        matrix_ref,
        DataArrayArtifact(
            schema=matrix_schema,
            variables={"readout_probability": [[0.99, 0.03], [0.01, 0.97]]},
        ).model_dump_json(by_alias=True),
    )
    storage.write_manifest(
        manifest.model_copy(
            update={
                "contents": (*manifest.contents, metrics_entry, matrix_entry),
            }
        )
    )


def attach_binary_artifact(project_root: Path, run_id: str) -> None:
    storage = sqlite_run_repository(project_root)
    manifest = storage.read_manifest(run_id)
    binary = RunContentEntry(
        role="artifact",
        id="binary-artifact",
        kind="binary",
        content_hash="binary-content",
        media_type="application/octet-stream",
    )
    binary_ref = artifact_storage_ref(binary)
    storage.write_bytes(run_id, binary_ref, b"\x00\x01")
    storage.write_manifest(
        manifest.model_copy(update={"contents": (*manifest.contents, binary)})
    )
