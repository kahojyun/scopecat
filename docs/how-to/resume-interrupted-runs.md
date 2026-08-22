# Resume an interrupted static run

Use resume when a notebook or executor disappeared after part of a static local
experiment became durable. The run must be `queued` or `attention_required` and
must not already have a terminal outcome.

First reconcile the physical instruments outside Scopecat. This means checking
that it is safe to acquire and program them again; durable measurement coverage
does not prove their current state.

Then rebuild the same invocation and resume the existing run:

```python
run = lab.get_run("01K...")
invocation = FREQUENCY_SCAN(
    device="q0",
    frequencies=frequencies,
)

run = lab.resume(run, invocation, executor_id="recovery-notebook")
```

Calling `lab.resume(...)` on an attention-required run is the explicit
authorization to leave quarantine after that external reconciliation. Scopecat
plans the invocation again against the run's accepted configuration snapshot.
The reconstructed durable request, run contract, and any initialized measurement
schema must match before attention is resolved or a new executor lease is
acquired.

Resume does not require a clean Git worktree and does not claim that source code,
imports, packages, or the Python environment are unchanged. Contract-compatible
changes are accepted. This is a deliberate recovery policy: the new execution
segment records the boundary, while the operator decides whether the current
code is appropriate.

For a supported static local run, execution starts at the durable contiguous
point watermark. Completed point effects are not replayed, and new measurements
belong to a new segment-owned fragment. The final dataset identity covers both
the old prefix and the new suffix.

Adaptive runs and domain-target runs cannot yet use this API after an execution
segment has started, even when zero points are durable. Their safe position also
depends on proposal or external-job state that point coverage alone cannot
identify. Close those runs or use target-specific recovery instead of replaying
them as static suffixes.
