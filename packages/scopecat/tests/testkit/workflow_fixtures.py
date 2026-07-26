from __future__ import annotations

from pathlib import Path

from scopecat.authoring import (
    ExperimentInvocation,
    QuantityType,
    ScalarType,
    parameter,
    record_product,
)
from scopecat.authoring.scans import axis
from scopecat.compiler.typed.program import CoreProgram
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.quantity import Quantity
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.runs.access import (
    artifact_storage_ref,
)
from tests.testkit.authoring import (
    DRIVE_FREQUENCY_POINT,
    SIMPLE_MODULE,
    link_invocation,
    template_fixture,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as WORKFLOW_FIXTURE_DIR
from tests.testkit.runtime import sqlite_run_repository


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(WORKFLOW_FIXTURE_DIR / "config-profile.json")


def load_experiment() -> CoreProgram:
    """Compile the simple-scan DSL fixture into a transient typed program."""

    return link_invocation(
        load_invocation(),
        config_profile=load_config(),
    ).program


def load_invocation() -> ExperimentInvocation:
    return template_fixture(
        SIMPLE_MODULE,
        id="test.workflow_scan",
        kind="simple_scan",
        required_inputs=("subject", "drive_frequency"),
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
    return config.model_copy(update={"system": system})


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
