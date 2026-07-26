"""Common execution persistence and raw dataset contract helpers."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.measurements.results import MeasurementRecord


def validate_run_measurements(
    *,
    measurements: Sequence[MeasurementRecord],
    expected_indices: set[int],
) -> list[Problem]:
    problems: list[Problem] = []
    seen_indices: set[int] = set()
    for measurement in measurements:
        if measurement.point_index in seen_indices:
            problems.append(
                _problem(
                    "execution_plan_measurement_point_duplicate",
                    "execution plan measurements repeat point index "
                    f"{measurement.point_index}",
                    "point_index",
                )
            )
        seen_indices.add(measurement.point_index)
        if measurement.point_index not in expected_indices:
            problems.append(
                _problem(
                    "execution_plan_measurement_point_unknown",
                    "execution plan measurements contain unknown point index "
                    f"{measurement.point_index}",
                    "point_index",
                )
            )
        if not measurement.observables:
            problems.append(
                _problem(
                    "execution_plan_measurement_observables_missing",
                    (
                        "execution plan measurement records require at least one "
                        "observable"
                    ),
                    "observables",
                )
            )
    return problems


def _problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PERSISTENCE,
        location=model_location("measurement_dataset", *path),
    )
