# Calibration State Shape Contract

Status: accepted design baseline
Date: 2026-06-27

This note records the calibration state decisions that build on the accepted
measurement, preview, and relation baselines. It decides whether
Scopecat needs a separate calibration-state category or whether calibration
should remain ordinary parameter state plus proposal, artifact, and registry
records.

The accepted direction is deliberately simple: accepted calibration is accepted
parameter state. Fit outputs, model results, quality metrics, and evidence
remain typed artifacts until a proposal is reviewed and activated through the
config registry.

## Current Baseline

The vNext exploratory calibration loop is:

- `Run.data()` reads measurement artifacts;
- notebook `Analysis` or a promoted `AnalysisStep` writes derived datasets,
  fit summaries, figures, quality evidence, and parameter guesses;
- `Analysis.candidate_config()` turns guesses into a candidate config review;
- review lowers that public candidate into internal `ParameterChangeSet`,
  review, finalization, and candidate `ConfigProfileSnapshot` artifacts;
- activation registers the candidate in the config registry and selects the
  active entry;
- future runs consume the active config registry entry;
- run comparison and reports reference the proposal, review, candidate config,
  active config, and activation records.

The current durable records already cover the lifecycle:

- `ParameterState`
- `ParameterBuildSnapshot`
- `ParameterPatch`
- `ParameterChangeSet`
- `ParameterProposalAcceptanceResult`
- `ConfigRegistryEntry`
- `ConfigRegistryRegistrationJob`
- `ConfigRegistryActiveState`
- `ConfigRegistryActivationRecord`
- analysis result artifacts
- run comparison and report records

There is no separate calibration-state record today.

## Durable Contract

The durable calibration contract is:

- Accepted calibration values are accepted `ParameterState` values inside a
  `ConfigProfileSnapshot`.
- Public calibration updates start as `Analysis.guess(...)` values and
  `CandidateConfig` objects.
- A calibration proposal is internally represented as a `ParameterChangeSet`.
- Calibration acceptance is candidate config review plus config registration
  and activation.
- Fit/model outputs are analysis artifacts, not accepted
  parameter state.
- Quality metrics, uncertainty, covariance, residuals, classifier thresholds,
  and model diagnostics stay in typed artifacts until a proposal policy chooses
  parameter patches.
- Rollback and active-state changes belong to the config registry.
- Reports and comparisons should cite the artifact/proposal/activation chain
  instead of reading hidden notebook variables or domain-local state.

Do not introduce a second accepted-state root such as `CalibrationState` for
values that can be represented as parameter scalars or parameter table rows.

## Accepted State

Accepted calibration is ordinary parameter state when it answers:

- what value should the next run use;
- which table row is currently accepted;
- which scalar or table value participates in planning;
- which accepted value should be diffed, reviewed, activated, rolled back, or
  compared.

Accepted calibration belongs in:

- scalar parameters for single accepted values;
- parameter tables for keyed device/resource/sample values;
- metadata only for non-planning annotations that do not need first-class
  validation or relation lookup.

Accepted calibration must not be hidden inside:

- processing result payloads;
- evaluation result payloads;
- report Markdown;
- domain package globals;
- runner adapter state;
- notebook-local variables.

## Artifact Outputs

Fit and model outputs remain artifacts when they answer:

- how was the accepted value computed;
- what model, bounds, residuals, covariance, confidence, or uncertainty were
  observed;
- what source measurements and analysis steps produced the result;
- which candidate updates were considered but not accepted;
- why a proposal was rejected, invalidated, or deferred.

These artifacts should carry:

- source run id;
- source artifact ids;
- analysis step id and version when reusable automation produced the result;
- model/function id;
- input parameters and bounds;
- output parameters with units;
- uncertainty/covariance/quality metrics where relevant;
- diagnostics;
- proposal ids generated from the artifact.

Artifacts may be domain-specific. They do not become core state unless multiple
domains need the same durable schema.

## Provenance Chain

Calibration provenance should be reconstructable from typed records:

1. source run manifest and `PlanSnapshot`;
2. raw measurement artifacts;
3. analysis artifacts for fit summaries, figures, quality metrics, and guesses;
4. internal `ParameterChangeSet`;
5. proposal review/finalization records;
6. candidate `ConfigProfileSnapshot`;
7. config registry entry and registration job;
8. active-state activation record;
9. follow-up run config source provenance;
10. comparison/report artifacts.

Cross-references should prefer artifact ids once manifest helpers make that
ergonomic. Path refs that remain in proposal and config records are local
cleanup debt, not a reason to invent calibration-specific ref lists.

## Rollback And Invalidation

Rollback belongs to the config registry:

- activating a config entry records the previous active entry;
- rollback activates the previous entry through a new activation record;
- reports and future runs can identify the active record used by a run;
- accepted parameter state is changed only by selecting a different active
  config snapshot.

Invalidation belongs to proposal/config workflow records:

- a proposal can become invalidated when its expected values no longer match
  the active state;
- a candidate config can become stale when its source active config changes;
- derived build outputs should be recomputed from the currently active
  `ParameterState`;
- calibration artifacts remain historical evidence even when their proposal is
  invalidated.

Do not delete or rewrite historical fit artifacts, proposals, reviews, or
activation records during rollback. Add new records that explain the lifecycle
transition.

## When A Separate Model May Be Needed

A future dedicated model may be justified for calibration evidence, not
accepted state, if multiple domains need the same schema for:

- fit result payloads;
- model selection records;
- covariance and uncertainty reports;
- classifier training reports;
- calibration campaign summaries;
- multi-run acceptance policies.

If introduced, those models should be artifact payloads or workflow records.
They should not replace `ParameterState` as the accepted planning input.

## Relationship To Related Contracts

Measurement storage:

- Measurement, table, array, and fit-result artifacts hold evidence and quality
  metrics.
- Accepted calibration values are parameter state, not measurement rows.

Relation execution:

- Domain fit/model functions may be registered as relation/function registry
  entries only when they are deterministic planning helpers.
- Analysis functions that consume measurement artifacts should be promoted as
  `AnalysisStep`s when they become reusable.

Plan preview storage:

- Candidate calibration previews may reuse preview table mechanics, but active
  calibration is still selected through config registry activation.

Diagnostics catalog:

- Calibration-related diagnostic families should cover stale proposal,
  expected-value mismatch, candidate config stale, activation failure, rollback
  failure, missing evidence artifact, and proposal policy rejection.

## Accepted Decisions

- Accepted calibration is accepted `ParameterState`.
- `ParameterChangeSet` remains the reviewable calibration update record.
- Fit/model outputs remain typed analysis artifacts.
- No separate `CalibrationState` root should be added for accepted values.
- Provenance must cross source run, artifacts, proposal, review, candidate
  config, registry entry, activation record, reports, and comparisons.
- Rollback uses config registry activation history.
- Historical calibration evidence remains immutable after rollback or
  invalidation.

## Deferred Questions

- Whether common fit-result payloads should become shared core artifact models.
- Whether campaign-level summaries need a core workflow record.
- Whether proposal invalidation should become automatic during acceptance
  preflight or remain explicit workflow behavior.
- Whether artifact ids should replace proposal/config path refs in the next
  implementation cleanup.
- Which calibration diagnostic codes should enter the future diagnostics
  catalog.
