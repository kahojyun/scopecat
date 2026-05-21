# Expected Calibration Work Continuation Review

## Fixture Wrapper

- expected output id: `calibration-continuation-review-gate-failed-fit.expected`
- status: `expected_validation_output`
- source fixture: `continuation-input.json`
- reference semantics: `fixture_paths_are_package_relative`

This is not a final runner framework, scheduler design, GUI design, storage
schema, parameter schema, retry policy, write-back policy, remote-execution
design, or hardware-control decision. The input is scattered continuation
context, not an executor log. Fixture path values are package-relative files
used for public-safe validation.

## Candidate Summary Review

### Episode

- episode: `cal-episode-04001`
- label: `qA tune-up continuation`
- target group: `qA`
- execution context: `local_user_python`, `notebook-like local session`
- intent: check resonator response, review Rabi amplitude fit, then continue to
  T1 only if the Rabi step is accepted

### Steps

- `step-1-resonator-check`: completed; continuation policy
  `continue_on_success`
- `step-2-rabi-amplitude`: review needed; continuation policy
  `pause_for_review_before_write`
- `step-3-t1-check`: blocked by `review:review-rabi-04002`; continuation
  policy `requires_prior_review_acceptance`

The fixture keeps calibration-specific step state explicit. It does not claim a
general workflow model or runner API.

### Outputs

- measurement `run-04001`: `qA resonator response check`
- measurement `run-04002`: `qA Rabi amplitude scan`
- parameter snapshots: `params-before-step-1`, `params-before-step-2`
- fit preview: `rabi-fit-preview-failed-quality`, `failed_quality_review`, not a durable
  analysis result, quality score `0.58` below threshold `0.8`

### Review Gates

- `review-rabi-04002`: user must decide whether to accept the proposed
  amplitude, rerun the Rabi step, or skip the target
- known context: Rabi measurement, fit preview, and parameter snapshot before
  the step
- missing or unverified: user acceptance for proposed pulse amplitude

### Declared Writes

- `write-qA-pulse-amplitude`: `qA.pulse.amplitude` from `0.42` to `0.49`
- status: `proposed_not_applied`
- authority: `user_authored_step_output`
- requires review: `review-rabi-04002`

The proposed parameter write is not a Scopecat-decided mutation.

### Requested Next Actions

- available: review the Rabi amplitude step
- available: accept the proposed value outside Scopecat after review
- available: rerun the Rabi amplitude step
- available: skip qA for this calibration episode
- blocked: continue to T1 check

### Attention

- `fit_failed_quality_review`: Rabi amplitude fit preview failed quality review.
- `downstream_step_blocked`: T1 check is blocked until review is resolved.
- `write_requires_review`: pulse amplitude write is proposed but not applied.

## Boundary Notes

- The fixture is state-only; it does not execute fixture code.
- The input does not already provide the candidate summary shape; it provides
  declared intent, planned steps, observed records, review state, and blocking
  facts that the summary organizes.
- `declared_step_plan` is interpretive context for this fixture, not a final
  authoring model or executor input contract.
- Calibration is the concrete workflow under validation. A more general
  episode/step/review model is not earned here.
- Scopecat is not deciding retry, mutation, write-back, scheduling, resource
  allocation, or hardware control.
- Review-needed and blocked states are ordinary calibration-continuation state.
  The warnings explain attention-worthy consequences, not normal lifecycle
  policy.

## Reviewer Questions

A reviewer should be able to answer:

- which calibration episode was being continued;
- which steps completed, need review, or are blocked;
- which measurements, fit preview, and parameter snapshots exist;
- whether a proposed parameter write was applied;
- what user decision is requested next;
- which manual choices are available and which continuation is blocked;
- that no runner, scheduler, automatic retry, or Scopecat-decided write-back
  has been accepted.
