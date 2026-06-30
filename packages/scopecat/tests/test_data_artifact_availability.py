from __future__ import annotations

from scopecat.models.data_artifact import (
    ArtifactRequirement,
    evaluate_artifact_availability,
)
from tests.support.records import assert_model_round_trip


def test_evaluate_artifact_availability_reports_point_eligibility() -> None:
    report = evaluate_artifact_availability(
        [
            {
                "point_id": 0,
                "trace": {"artifact_ref": "artifacts/point-0-trace.bin"},
                "preview": {"artifact_ref": "artifacts/point-0-preview.json"},
            },
            {
                "point_id": 1,
                "trace": {"artifact_ref": "artifacts/point-1-trace.bin"},
            },
            {
                "point_id": 2,
                "preview": {"artifact_ref": "artifacts/point-2-preview.json"},
            },
        ],
        [
            ArtifactRequirement(label="trace"),
            ArtifactRequirement(label="preview", required=False),
        ],
        point_count=3,
    )

    assert_model_round_trip(
        report,
        schema_version="scopecat.artifact_availability_report.v1",
    )
    assert report.eligible_point_ids == [0, 1]
    assert report.partial_point_ids == [1]
    assert [
        (
            point.point_id,
            point.available,
            point.missing_required,
            point.missing_optional,
            point.eligible,
        )
        for point in report.points
    ] == [
        (0, ["trace", "preview"], [], [], True),
        (1, ["trace"], [], ["preview"], True),
        (2, ["preview"], ["trace"], [], False),
    ]
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "missing_optional_artifact",
        "missing_required_artifact",
    ]


def test_evaluate_artifact_availability_reports_invalid_point_rows() -> None:
    report = evaluate_artifact_availability(
        [
            {"point_id": "0", "trace": {"artifact_ref": "artifacts/invalid.bin"}},
            {"point_id": 0, "trace": {"artifact_ref": "artifacts/point-0.bin"}},
            {"point_id": 0, "trace": {"artifact_ref": "artifacts/duplicate.bin"}},
            {"point_id": 3, "trace": {"artifact_ref": "artifacts/out.bin"}},
            {"point_id": 1, "trace": {"artifact_ref": "   "}},
        ],
        [ArtifactRequirement(label="trace")],
        point_count=2,
    )

    assert report.eligible_point_ids == [0]
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "invalid_artifact_point",
        "duplicate_artifact_point",
        "invalid_artifact_point",
        "missing_required_artifact",
    ]
    assert [
        (point.point_id, point.available, point.missing_required, point.eligible)
        for point in report.points
    ] == [
        (0, ["trace"], [], True),
        (1, [], ["trace"], False),
    ]
