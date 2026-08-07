# Adaptive experiments

Use a staged experiment when each new point depends on measurements from an
earlier point. Every stage is an ordinary durable run; the notebook callback
decides whether to create the next one.

```python
def choose_next(stage):
    data = stage.run.measurements()
    candidate = optimizer.ask(data)
    return None if candidate is None else point_experiment(candidate)

sequence = lab.run_staged(
    point_experiment(initial_point),
    next_stage=choose_next,
    max_stages=20,
)
```

The callback can inspect the latest run through `stage.run` and earlier stages
through `stage.history`. Returning `None` finishes the sequence. `max_stages`
bounds an optimizer that keeps proposing work; when the bound is reached, the
callback for the final completed stage is deferred so stateful optimizers do not
advance beyond durable work.

Sequences retain their configuration snapshot and typed run lineage. They can
be rediscovered and continued after restarting a notebook:

```python
sequences = lab.staged_experiments()  # newest sequence first
sequence = lab.get_staged_experiment(sequences[0].sequence_id)

continued = lab.resume_staged(
    sequence.sequence_id,
    next_stage=choose_next,
    max_stages=10,  # bounds newly executed stages
)
```

Resume first calls the callback with the latest successfully completed stage,
including a callback deferred by an earlier limit, and then executes newly
proposed stages. Rediscovered sequences report `stopped_by_limit` as `None`
because run lineage is durable but the previous notebook loop's stop reason is
not.

The current boundary deliberately keeps orchestration decisions in Python:
completed stages, measurements, configuration, and lineage are durable, while
the callback and optimizer state remain notebook-owned. A sequence can be
inspected and explicitly resumed after a notebook restart.
