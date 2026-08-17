from pathlib import Path

from scopecat.records.content import ContentEntry
from scopecat.runs.access import artifact_storage_ref

from scopecat_testkit.server.runtime import sqlite_run_repository


def attach_binary_artifact(project_root: Path, run_id: str) -> None:
    storage = sqlite_run_repository(project_root)
    manifest = storage.read_manifest(run_id)
    binary = ContentEntry(
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
