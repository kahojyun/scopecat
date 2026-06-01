# Calibration Step Observation Link Validation Result

## Status

Implementation candidate validated.

This result validates one narrow calibration-to-measurement bridge:
**Calibration Step Observation Link**.

It is a workflow-pressure slice, not a final calibration step schema,
measurement-record schema, relation graph, fitting framework, executor,
scheduler, write-back contract, hardware-control contract, workflow DAG, or
GUI design.

Artifact posture: `internal_validation_summary`. This validation result, its
fixture input, and expected output are repository-safe discovery artifacts, not
portable/public export artifacts.

## Fixture

Fixture:
[`../../tests/fixtures/calibration_step_observation_link/basic_observation/`](../../../../tests/fixtures/calibration_step_observation_link/basic_observation)

Implementation candidate:
[`../../implementation_candidates/calibration_step_observation_link/`](../../../../implementation_candidates/calibration_step_observation_link)

The fixture records two calibration step intents:

- a qA Rabi amplitude planned observation for fit input;
- a qA T1 planned observation for review evidence.

It then records two calibration step records:

- one step record links a preview-ready measurement-record summary as the
  observed Rabi output;
- one step record reports the planned T1 measurement observation as missing.

The linked measurement facts are copied only as review-summary projections.
Measurement Records remains the owner of primary data, preview, storage,
import, export, and measurement validity behavior.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- keep calibration step intent as prospective observation need;
- keep calibration step record as retrospective observation summary;
- link a calibration step record to a measurement record as observed output or
  fit input;
- project only measurement-record summary facts into calibration review;
- surface missing measurement observations as review findings;
- reject fixture claims that cross into measurement payload reads, preview
  inference, fitting, calibration execution, continuation decisions, parameter
  write-back, hardware control, scheduling, or shared relation graphs.

## Boundary

This slice validates explicit observation links only.

It does not:

- define final calibration step, measurement record, relation graph, lifecycle,
  storage, or package schemas;
- read primary measurement data or measurement payloads;
- infer preview metadata;
- run fitting, scoring, or scientific validity checks;
- execute calibration code or measurement code;
- decide continuation, retry, skip, or remeasurement;
- propose, accept, apply, or roll back parameter writes;
- control hardware;
- schedule work;
- recursively traverse adjacent records;
- define a GUI workflow.

## Result

Calibration and measurement can be linked without merging ownership.

Calibration step records can reference measurement records as observed outputs
or fit inputs. That gives calibration workflows enough evidence to explain what
observation was available or missing, while preserving Measurement Records as
the owner of primary data and measurement validity.

Missing measurement observations remain review findings. They do not become
automatic retries, step failures, continuation decisions, write-back behavior,
or hardware-control instructions.

## Follow-Up

Stop this slice at observation links unless a concrete workflow needs stronger
behavior.

Likely follow-up slices should stay separate:

- calibration step intent resolution to execution record, if step context
  selectors need the same intent-versus-record treatment validated for
  measurements;
- calibration fit-result reference shape, still without fitting execution or
  score semantics;
- reviewable proposed-write linkage from a step record, still without applying
  writes;
- step-level context-link comparison only after more calibration fixtures need
  comparison, not as a shared relation graph.
