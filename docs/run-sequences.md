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

When a policy decision must be audited, return a structured proposal:

```python
from scopecat.api.lab import SequenceProposal


def choose_next(sequence_run):
    candidate = optimizer.ask(sequence_run.measurements())
    if candidate is None:
        return None
    return SequenceProposal(
        experiment=calibration_experiment(candidate),
        policy_id="resonance-search",
        policy_version="2",
        decision={"candidate_hz": candidate.frequency_hz},
        checkpoint=optimizer.checkpoint(),
    )
```

The policy identity, decision summary, and JSON checkpoint become part of the
next run's typed lineage. The completed run that the policy evaluated owns a
`run-sequence-transition` artifact recording `proposed`, `stopped`,
`budget_exhausted`, or `policy_failed`. Plain invocation returns remain the
short path.

Sequences can be rediscovered with `lab.run_sequences()` or
`lab.get_run_sequence(sequence_id)`. Their current status is derived from the
latest run's transition, rather than from an in-memory loop flag. A latest run
without a transition is `awaiting_decision`.

The callback implementation remains notebook-owned. Durable state includes the
runs, accepted configurations, lineage, and policy transitions; arbitrary
Python closures and live optimizer objects are not serialized. A future
in-run adaptive point plan should therefore be a separate abstraction with
streaming and executor semantics, not an extension of `RunSequence`.
