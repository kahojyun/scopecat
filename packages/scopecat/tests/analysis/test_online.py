import pytest

from scopecat.analysis import decide_online_convergence


def test_decide_online_convergence_stops_when_tail_is_stable() -> None:
    decision = decide_online_convergence(
        [
            {"point_index": 2, "x": 2.0, "score": 1.001},
            {"point_index": 0, "x": 0.0, "score": 0.7},
            {"point_index": 1, "x": 1.0, "score": 1.0},
            {"point_index": 1, "x": 1.0, "score": 9.0},
            {"point_index": 10, "x": 10.0, "score": 0.0},
            {"point_index": "3", "x": 3.0, "score": 1.0},
        ],
        point_count=3,
        x_column="x",
        y_column="score",
        min_points=3,
        tolerance=0.01,
        window=2,
    )

    assert decision.stop is True
    assert decision.evaluation_status == "evaluated"
    assert decision.completed_point_indices == (0, 1, 2)
    assert decision.reason == "last 2 'score' values within 0.01"
    assert decision.problems == ()


def test_decide_online_convergence_reports_insufficient_points() -> None:
    decision = decide_online_convergence(
        [
            {"point_index": 0, "x": 0.0, "score": 0.7},
            {"point_index": 3, "x": 3.0, "score": 1.0},
        ],
        point_count=3,
        x_column="x",
        y_column="score",
        min_points=2,
        tolerance=0.01,
    )

    assert decision.stop is False
    assert decision.evaluation_status == "collecting"
    assert decision.completed_point_indices == (0,)
    assert decision.problems == ()


def test_decide_online_convergence_reports_invalid_rows() -> None:
    decision = decide_online_convergence(
        [
            {"point_index": 0, "x": 0.0, "score": 0.7},
            {"point_index": 1, "score": 0.8},
            {"point_index": 2, "x": 2.0, "score": "0.9"},
        ],
        point_count=3,
        x_column="x",
        y_column="score",
        min_points=3,
        tolerance=0.01,
    )

    assert decision.stop is False
    assert decision.evaluation_status == "invalid"
    assert decision.completed_point_indices == (0, 1, 2)
    assert [problem.code for problem in decision.problems] == [
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
