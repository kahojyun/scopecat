"""Physical sample identity and descriptive metadata contracts."""

import pytest
from pydantic import ValidationError

from scopecat.records.sample import SampleArtifactRef, SampleRecord


def test_sample_record_requires_url_safe_identity() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        SampleRecord(id="chip/unsafe", kind="chip", active_revision=1)


def test_sample_artifact_id_is_a_local_non_empty_key() -> None:
    artifact = SampleArtifactRef(
        id="top view/report",
        title="Top-view report",
        uri="https://example.test/reports/top-view",
    )

    assert artifact.id == "top view/report"
