# Expected Parameter State Management Review

## Fixture Wrapper

- expected output id: `parameter-seed-review-commit.expected`
- status: `expected_validation_output`
- source fixture: `parameter-state-input.json`
- guard: This expected output is not a final parameter schema, branch model,
  tag model, commit model, hardware write-back contract, schema migration
  contract, or GUI design.

## Candidate Summary Review

### Lineage

- lineage: `lineage-qA-default-bias`
- label: qA default bias calibration
- purpose: `working_point`
- purpose kind: domain label
- target scope: `sample-alpha`, `qA`, `default_bias`

Working point is one possible purpose label for a named parameter state
lineage. It is not the generic branch model.

### States

| State | Role | Parent | Readiness | Trust | History plotting |
| --- | --- | --- | --- | --- | --- |
| `param-state-0001` | base seed state | none | `seeded_incomplete` | `not_fully_trusted` | exclude from trusted drift plots |
| `param-state-0002` | committed parameter state | `param-state-0001` | `partially_calibrated` | `trusted_for_declared_scope` | include declared trusted entries only |

The copied seed is useful as a starting point, but it should not be plotted or
reported as trusted calibrated truth. The committed state is trusted only for
the declared entries accepted by review.

### Reviewable Diff

Review `review-change-0001` accepted draft `draft-change-0001` and created
committed state `param-state-0002`.

| Kind | Path | Old | New | Unit |
| --- | --- | --- | --- | --- |
| changed | `qubits.qA.drive_frequency_hz` | `5010000000` | `5012500000` | Hz |
| changed | `qubits.qA.pi_amp` | `0.38` | `0.42` | arb |
| added | `readout.qA.discrimination_threshold` | none | `0.17` | arb |

The added parameter tests small exploratory schema pressure. It does not earn
general schema migration.

### Draft History

- draft `draft-change-0001` was accepted by review, but is not durable history
  by itself.
- durable history starts when review `review-change-0001` is accepted and
  committed state `param-state-0002` exists.

### Measurement Reference

- measurement: `measurement-03001`
- experiment: qA Rabi confirmation
- selected parameter state: `param-state-0002`
- selection time: `2026-05-19T14:10:00`
- hardware state claim: `not_recorded`

The measurement selected a parameter state at start. This fixture does not
claim that Scopecat knows current instrument state.

## Boundary Notes

- external JSON overwrite behavior is evidence of current practice, not the
  desired product model.
- branch, tag, commit, merge, rebase, rollback, and proposal-branch semantics
  remain undecided.
- hardware write-back, instrument state tracking, drift plotting, schema
  migration, and GUI behavior remain out of scope.

## Reviewer Questions

A reviewer should be able to answer:

- which lineage the state belongs to;
- why `working_point` is a purpose label rather than the generic branch model;
- why the seed state is not trusted calibrated truth;
- which parameters changed or were added;
- which review created the committed state;
- which state the measurement selected at start;
- that no current hardware state or write-back claim is made.
