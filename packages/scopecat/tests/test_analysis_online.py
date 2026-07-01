import pytest

from scopecat.analysis import EarlyStopDecision, decide_online_convergence


def test_decide_online_convergence_stops_when_tail_is_stable() -> None:
    decision = decide_online_convergence(
        [
            {"point_id": 2, "x": 2.0, "score": 1.001},
            {"point_id": 0, "x": 0.0, "score": 0.7},
            {"point_id": 1, "x": 1.0, "score": 1.0},
            {"point_id": 1, "x": 1.0, "score": 9.0},
            {"point_id": 10, "x": 10.0, "score": 0.0},
            {"point_id": "3", "x": 3.0, "score": 1.0},
        ],
        point_count=3,
        x_column="x",
        y_column="score",
        min_points=3,
        tolerance=0.01,
        window=2,
    )

    restored = EarlyStopDecision.model_validate_json(decision.model_dump_json())

    assert restored == decision
    assert decision.schema_version == "scopecat.early_stop_decision.v1"
    assert decision.stop is True
    assert decision.completed_point_ids == [0, 1, 2]
    assert decision.reason == "last 2 'score' values within 0.01"
    assert decision.diagnostics == []


def test_decide_online_convergence_reports_insufficient_points() -> None:
    decision = decide_online_convergence(
        [
            {"point_id": 0, "x": 0.0, "score": 0.7},
            {"point_id": 3, "x": 3.0, "score": 1.0},
        ],
        point_count=3,
        x_column="x",
        y_column="score",
        min_points=2,
        tolerance=0.01,
    )

    assert decision.stop is False
    assert decision.completed_point_ids == [0]
    assert [diagnostic.code for diagnostic in decision.diagnostics] == [
        "insufficient_convergence_points",
    ]


def test_decide_online_convergence_reports_invalid_rows() -> None:
    decision = decide_online_convergence(
        [
            {"point_id": 0, "x": 0.0, "score": 0.7},
            {"point_id": 1, "score": 0.8},
            {"point_id": 2, "x": 2.0, "score": "0.9"},
        ],
        point_count=3,
        x_column="x",
        y_column="score",
        min_points=3,
        tolerance=0.01,
    )

    assert decision.stop is False
    assert decision.completed_point_ids == [0, 1, 2]
    assert [diagnostic.code for diagnostic in decision.diagnostics] == [
        "missing_convergence_column",
        "invalid_convergence_value",
    ]


def test_decide_online_convergence_rejects_invalid_policy() -> None:
    with pytest.raises(ValueError, match="min_points and window must be positive"):
        decide_online_convergence(
            [],
            point_count=1,
            x_column="x",
            y_column="score",
            min_points=0,
            tolerance=0.01,
        )

    with pytest.raises(ValueError, match="tolerance must be nonnegative"):
        decide_online_convergence(
            [],
            point_count=1,
            x_column="x",
            y_column="score",
            min_points=1,
            tolerance=-0.01,
        )
