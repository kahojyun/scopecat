# Adaptive experiments

Use a staged experiment when each new point depends on measurements from an
earlier point. Every stage is an ordinary durable run; the notebook callback
decides whether to create the next one.

```python
def choose_next(stage):
    data = stage.measurements()
    candidate = optimizer.ask(data)
    return None if candidate is None else point_experiment(candidate)


sequence = lab.run_staged(
    point_experiment(initial_point),
    next_stage=choose_next,
    max_stages=20,
)
```

The callback reads the latest dataset through `stage.measurements()`, inspects
other run facts through `stage.run`, and reaches earlier runs through
`stage.history`. Returning `None` finishes the sequence. `max_stages`
bounds an optimizer that keeps proposing work; when the bound is reached, the
callback for the final completed stage is deferred so stateful optimizers do not
advance beyond durable work.

When a policy must survive or be audited across notebook restarts, return a
structured proposal instead of only the invocation:

```python
from scopecat.api.lab import StageProposal


def choose_next(stage):
    optimizer.restore(stage.decision.checkpoint if stage.decision else {})
    candidate = optimizer.ask(stage.measurements())
    if candidate is None:
        return None
    return StageProposal(
        experiment=point_experiment(candidate),
        policy_id="resonance-search",
        policy_version="2",
        decision={"candidate_hz": candidate.frequency_hz},
        checkpoint=optimizer.checkpoint(),
    )
```

The policy identity, decision summary, and JSON checkpoint become part of the
next run's durable stage lineage. The completed run that the policy evaluated
also owns a `stage-sequence-event` artifact recording whether the policy
proposed work, stopped, reached the execution bound, or failed. Plain
invocation returns remain the short path. Arbitrary callback closures and
optimizer objects are never serialized.

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
proposed stages. `sequence.events` exposes the durable event log and
`sequence.status` summarizes its latest event as `proposed`, `stopped`,
`paused`, or `failed`. Consequently, rediscovered sequences retain whether the
previous notebook loop stopped normally or reached its bound; legacy sequences
without an event remain `active` with an unknown `stopped_by_limit` value.

The current boundary deliberately keeps policy execution in Python: completed
stages, measurements, configuration, lineage, and policy outcomes are durable,
while the callback implementation and live optimizer object remain
notebook-owned. A sequence can be inspected and explicitly resumed after a
notebook restart.
