"""Define reusable template and one-off scratch experiments over one body."""

from __future__ import annotations

# %%
from collections.abc import Sequence

import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.workflows.fake_x_count_experiment import (
    DEFAULT_X_COUNTS,
    X_COUNT,
    fake_x_count_capture,
)


def x_count_body(x_counts: Sequence[int]) -> sc.ExperimentBody:
    capture = fake_x_count_capture(x_count=X_COUNT)
    return (
        sc.experiment(capture)
        .scan(X_COUNT, tuple(x_counts))
        .record_product(
            capture.products.probability_0,
            capture.products.probability_1,
        )
    )


# %%
@sc.template
def fake_x_count_template() -> sc.ExperimentBody:
    """Close reusable defaults into a template that can be prepared repeatedly."""

    return x_count_body(DEFAULT_X_COUNTS)


@sc.scratch
def fake_x_count_scratch(
    *,
    x_counts: Sequence[int],
) -> sc.ExperimentBody:
    """Build one workspace-neutral invocation from caller-selected points."""

    return x_count_body(x_counts)


# %%
lab = quantum_lab(workspace=notebook_workspace("authoring-template-and-scratch"))
template_experiment = lab.prepare(fake_x_count_template())
template_preview = template_experiment.preview()
template_run = template_experiment.run(
    name="fake AWG X-count template",
    tags=("authoring", "template"),
)

scratch_experiment = lab.prepare(fake_x_count_scratch(x_counts=(0, 1, 3, 5)))
scratch_preview = scratch_experiment.preview()
scratch_run = scratch_experiment.run(
    name="fake AWG X-count scratch",
    tags=("authoring", "scratch"),
)

# %%
authoring_summary = {
    "template_status": template_run.manifest.status,
    "scratch_status": scratch_run.manifest.status,
    "template_points": template_preview.point_count,
    "scratch_points": scratch_preview.point_count,
}
print(authoring_summary)
