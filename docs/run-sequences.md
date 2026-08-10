# Run sequences

Use a run sequence when a calibration or tune-up consists of several ordinary
runs and each run may choose what should run next. A sequence is a durable,
linear collection of independent runs. It is not an optimizer that injects new
points into an already executing run.

```python
def choose_next(sequence_run):
    data = sequence_run.measurements()
    candidate = calibration_policy(data)
    return None if candidate is None else calibration_experiment(candidate)


sequence = lab.run_sequence(
    calibration_experiment(initial_candidate),
    next_run=choose_next,
    max_runs=20,
)
```

The callback receives a completed `SequenceRun`. Its `run` is the ordinary run
handle, `measurements()` loads that run's dataset, `previous_run` identifies its
predecessor, and `history` contains the completed run handles in order. Returning
`None` records a terminal `stopped` transition.

`max_runs` is the persistent scientific budget. It is stored in every run's
sequence lineage and cannot change when the sequence is resumed. Reaching it
records a terminal `budget_exhausted` transition.

For operational chunking, `max_new_runs` limits only the work performed by one
method call:

```python
partial = lab.run_sequence(
    calibration_experiment(initial_candidate),
    next_run=choose_next,
    max_runs=20,
    max_new_runs=3,
)

continued = lab.resume_sequence(
    partial.sequence_id,
    next_run=choose_next,
    max_new_runs=3,
)
```

Stopping at `max_new_runs` does not change the scientific budget and does not
write a scientific transition. The latest run remains `awaiting_decision`, so a
later call can continue it. This keeps process scheduling separate from the
meaning of the experiment.

When the next run should use a different accepted config snapshot, return a
structured proposal:

```python
from scopecat.api.lab import SequenceProposal


def choose_next(sequence_run):
    analysis = sequence_run.run.analyze(calibration_analysis())
    return SequenceProposal(
        experiment=verification_experiment(),
        config=analysis.candidate_config(),
    )
```

The candidate configuration is resolved for the proposed run without changing
the project's active configuration. Later plain proposals inherit that accepted
snapshot until another structured proposal selects a different one. A sequence
therefore models calibration and verification runs honestly instead of assuming
that every run uses one global config.

The completed run evaluated by the callback owns a `run-sequence-transition`
artifact recording `proposed`, `stopped`, `budget_exhausted`, or
`proposal_failed`. A proposed transition includes the next experiment, config
provenance, normalized request hash, and deterministic proposal identity. If
execution is interrupted after recording the proposal, resume reruns the
notebook callback but proceeds only when it reproduces that same durable request
and configuration. Plain invocation returns remain the short path.

Sequences can be rediscovered with `lab.run_sequences()` or
`lab.get_run_sequence(sequence_id)`. Their current status is derived from the
latest run's transition, rather than from an in-memory loop flag. A latest run
without a transition is `awaiting_decision`.

Results remain grouped by run because different sequence runs may use different
experiments or result schemas:

```python
results = sequence.results()
historical_views = results.stored

# When every run used the same authored result schema:
typed_views = results.bind(calibration_experiment().output)
```

`datasets`, `stored`, and `bind(...)` all preserve sequence order and run
boundaries. Combining rows from heterogeneous runs is an explicit analysis
choice rather than an implicit concatenation.

The callback implementation and all long-lived workflow state remain
notebook-owned. Durable sequence facts include the runs, accepted
configurations, lineage, and next-run transitions; arbitrary Python closures,
optimizer checkpoints, calibration conclusions, schedules, and approval state
are not sequence state.

This is the deliberate stopping point for `RunSequence`. Workflow definitions,
workflow-owned state, branching, retry policy, calibration recommendations, and
periodic scheduling should be designed from complete bring-up and recurring
calibration workflows instead of being added to this linear primitive. A future
in-run adaptive point plan is likewise a separate abstraction with streaming
and executor semantics.
