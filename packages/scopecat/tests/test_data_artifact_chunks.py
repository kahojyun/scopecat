from __future__ import annotations

import pytest

from scopecat.models.data_artifact import ArtifactChunk, assemble_chunked_artifact
from tests.support.records import assert_model_round_trip


def test_assemble_chunked_artifact_builds_complete_manifest() -> None:
    manifest = assemble_chunked_artifact(
        "artifacts/raw-values.bin",
        [
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=1,
                values=[3, 4],
                final=True,
            ),
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=0,
                values=[1, 2],
            ),
        ],
    )

    restored = assert_model_round_trip(
        manifest,
        schema_version="scopecat.chunked_artifact_manifest.v1",
    )

    assert restored == manifest
    assert manifest.complete is True
    assert manifest.value_count == 4
    assert [chunk.index for chunk in manifest.chunks] == [0, 1]
    assert manifest.diagnostics == []


def test_assemble_chunked_artifact_reports_incomplete_chunk_sets() -> None:
    manifest = assemble_chunked_artifact(
        "artifacts/raw-values.bin",
        [
            ArtifactChunk(
                artifact_ref="artifacts/other.bin",
                index=0,
                values=[0],
            ),
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=-1,
                values=[-1],
            ),
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=0,
                values=[1],
            ),
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=0,
                values=[2],
            ),
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=2,
                values=[3],
                final=True,
            ),
        ],
    )

    assert manifest.complete is False
    assert manifest.value_count == 2
    assert [chunk.index for chunk in manifest.chunks] == [0, 2]
    assert [diagnostic.code for diagnostic in manifest.diagnostics] == [
        "chunk_artifact_mismatch",
        "invalid_artifact_chunk",
        "duplicate_artifact_chunk",
        "missing_artifact_chunks",
    ]


def test_assemble_chunked_artifact_reports_ambiguous_final_chunks() -> None:
    manifest = assemble_chunked_artifact(
        "artifacts/raw-values.bin",
        [
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=0,
                values=[1],
                final=True,
            ),
            ArtifactChunk(
                artifact_ref="artifacts/raw-values.bin",
                index=1,
                values=[2],
                final=True,
            ),
        ],
    )

    assert manifest.complete is False
    assert [diagnostic.code for diagnostic in manifest.diagnostics] == [
        "multiple_final_artifact_chunks",
    ]


def test_assemble_chunked_artifact_requires_positive_expected_chunks() -> None:
    with pytest.raises(ValueError, match="expected_chunks must be positive"):
        assemble_chunked_artifact(
            "artifacts/raw-values.bin",
            [],
            expected_chunks=0,
        )
