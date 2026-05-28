# Calibration Fit Validation Dataset

## Status

Evidence-backed problem brief with project-owner clarification.

## User-Facing Failure

Users do not only need to know that a fit failed. They need a continuous way to
recover the calibration workflow and optionally keep the failed or suspicious
case for later fit-code improvement.

The immediate response depends on the observed data:

- if the data has no meaningful signal, the user usually needs to adjust
  experiment parameters and remeasure;
- if the data has a meaningful signal but the fit fails, the user may adjust
  ROI, outlier treatment, or initial guesses and refit;
- if the case is useful for future improvement, the user may add the data,
  review label, fit-code reference, and fit context to a lab-internal
  validation dataset.

The current gap is not that users lack a way to write fitting code. The gap is
that suspicious cases are easy to lose while the user is trying to keep the
experiment moving.

## Observed Sample Evidence

- Existing calibration evidence already mixes measurement data, fit output,
  operator judgment, and direct parameter mutation.
- Sample fit utilities contain user-owned models, initial-guess logic, batch
  fitting, fit reports, residual-like scores, stderr capture, failed-fit
  warnings, neighboring-parameter refits, and outlier replacement.
- Sample calibration and analysis code contains explicit failure checks such as
  covariance/variance thresholds, unacceptable relative error, and manual
  review-like comments.
- Readout analysis code computes domain-specific outputs such as SNR,
  visibility, fidelity, classifier centers, assignment fidelity, and fit-score
  style diagnostics.
- Gate, resonator, coherence, readout, and XEB-style helpers show that fit
  families and quality signals differ by workflow. A single Scopecat-defined
  fit score would be premature.

## Project-Owner Clarification

- Final fitting should remain user-owned. Scopecat should not implement complex
  fitting routines or define authoritative calibration scores.
- Scopecat can help users mark fit outcomes, identify candidate cases, and
  build validation datasets for later user-code improvement.
- The first user action after a failed fit is often to continue the experiment:
  remeasure if there is no signal, or refit with adjusted ROI or initial guess
  if there is a clear signal.
- Dataset capture should fit into that recovery flow. Users should not need a
  separate complex search process to rediscover cases worth adding.
- Lab-internal sharing is valuable, but it is a distinct boundary from public
  export or published documentation.

## Derived Hypotheses

- A useful first workflow is a fit-case candidate queue, not a fitting engine:
  Scopecat records user-owned fit outcomes and offers low-friction promotion to
  a validation dataset.
- Candidate triggers may include fit exception, failed user threshold,
  suspicious user mark, manual ROI adjustment, initial-guess override,
  operator rerun decision, accepted-after-review fit, or large mismatch between
  clear signal and failed fit.
- Validation cases should record enough context for later replay by user code:
  measurement data reference, declared scan/preview metadata, fit family,
  user fit-code reference, fit config or initial guess, review label, optional
  ROI/outlier notes, fit output, and expected regression behavior.
- Scopecat should distinguish workflow recovery from dataset curation. A
  remeasure recommendation, a refit attempt, and "add to validation dataset"
  are related but different user choices.
- The first dataset posture should be lab-internal validation, not public
  export. Portable or externally shared datasets need explicit artifact
  boundary and redaction classification.

## Out Of Scope For This Brief

- Scopecat-owned fit implementation, model selection, fit scoring, or
  calibration correctness judgment.
- Scopecat-decided parameter write-back, automatic retry, autonomous
  remeasurement, or hardware-control decisions.
- A universal fit-result schema that covers all calibration families.
- Treating every temporary fit preview as a durable validation case.
- Public/export dataset format before a lab-internal validation workflow is
  validated.

## Possible Validation Questions

- Can Scopecat help users recover from failed or suspicious fits while making
  it easy to save selected cases into a lab-internal validation dataset?
- Can a candidate queue preserve useful fit-failure context without Scopecat
  executing fits or defining quality scores?
- What minimal case record lets users rerun improved fit code against prior
  suspicious cases and understand whether the new code covers the failure mode?
- Which labels and trigger reasons are useful enough for calibration review
  without becoming a domain-judgment engine?

## Candidate Labels

Initial labels should remain user-facing and workflow-oriented:

| Label | Meaning |
| --- | --- |
| `no_signal_remeasure` | Data lacks a meaningful signal; user likely needs remeasurement. |
| `signal_fit_failed` | Signal is visible but the current fit failed. |
| `roi_adjusted_refit` | User changed ROI or selected points before refitting. |
| `initial_guess_adjusted_refit` | User changed initial guess or bounds before refitting. |
| `fit_repaired` | User-owned adjustment made a previously failed fit usable enough for review. |
| `outlier_sensitive` | Fit result changes materially after outlier handling. |
| `accepted_after_review` | User accepted the result after manual review. |
| `rerun_required` | User decided the measurement should be repeated. |
| `add_to_validation_dataset` | User selected the case for later fit-code validation. |
