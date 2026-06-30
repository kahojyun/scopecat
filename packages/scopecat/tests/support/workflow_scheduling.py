from __future__ import annotations

from scopecat.experiments import acquire, experiment, plan_experiment
from scopecat.relations import ParameterRelationData, grid


def plan():
    spec = experiment(
        id="timing-boundary",
        kind="workflow.timing",
        points=grid(point=[0, 1, 2]),
        acquire=acquire("measurement"),
    )
    return plan_experiment(spec, params=ParameterRelationData())
