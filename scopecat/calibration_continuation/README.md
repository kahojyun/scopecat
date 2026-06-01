# Calibration Continuation Engineering Prototype

This route-local module promotes the narrow accepted calibration continuation
review surface into production-shaped prototype code.

The accepted boundary is intentionally small:

```text
declared calibration review-state summary
  -> declared calibration-derived parameter-state backbone context
  -> declared backbone context findings
  -> local notebook/CLI-shaped review surface
  -> labels-only action palette
  -> review-only action recording
```

The prototype is a local `review_summary` projection. It does not execute
notebook cells, render GUI components, read measurement payloads, run fitting,
execute calibration steps, schedule work, write parameters, apply hardware
state, start measurements, mutate storage, or define a shared calibration,
measurement, prepared-run, or parameter-state schema.

The review surface composes prior declared summaries into route header facts,
step review cards, backbone context facts, backbone findings, and labels-only
actions. The action-recording surface accepts explicit user-declared choices
against those labels and records audit intent only. A recorded choice does not
advance workflow state or perform the named action.

The promoted boundary is owned by
[`../../docs/architecture/calibration-continuation/engineering-prototype-promotion-decision.md`](../../docs/architecture/calibration-continuation/engineering-prototype-promotion-decision.md).

## API Surface

Current local surface:

- `CalibrationContinuationReviewSurfaceRequest.from_dict(...)`;
- `compose_calibration_continuation_review_surface(...)`;
- `CalibrationContinuationReviewSurfaceResult.to_dict()`;
- `build_calibration_continuation_review_surface_summary(...)`;
- `CalibrationReviewActionRecordingRequest.from_dict(...)`;
- `record_calibration_review_actions(...)`;
- `CalibrationReviewActionRecordingResult.to_dict()`;
- `build_calibration_review_action_recording_summary(...)`.

The typed request/result objects are the route-local engineering objects. Raw
dictionary builders remain only as edge adapters for fixture parity and current
callers.
