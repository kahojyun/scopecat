# Adapter-Authored Parameter Compatibility Output Preview Validation Result

## Status

Exploratory implementation candidate validated.

This is not an ADR, compatibility-output writer, adapter execution contract,
file-observation contract, hardware-control contract, parameter write-back
contract, durable storage contract, GUI design, managed runner, or stable
public adapter API.

Boundary clarification:
[`parameter-compatibility-artifacts-boundary-clarification.md`](parameter-compatibility-artifacts-boundary-clarification.md)
supersedes this slice as active route guidance. The managed parameter-state
snapshot is the canonical run context; adapter-authored compatibility output
manifests remain optional derivative debug/handoff evidence, not required
measurement context and not a Scopecat-owned compatibility-output workflow.

## Inputs

- [`approved-parameter-compatibility-adapter-request-validation-result.md`](approved-parameter-compatibility-adapter-request-validation-result.md)
- [`adapter-authored-parameter-state-import-preview-validation-result.md`](adapter-authored-parameter-state-import-preview-validation-result.md)
- [`parameter-write-compatibility-output-validation-result.md`](parameter-write-compatibility-output-validation-result.md)
- [`adapter-authored-parameter-compatibility-output-preview-validation-plan.md`](adapter-authored-parameter-compatibility-output-preview-validation-plan.md)
- `tests/fixtures/adapter_authored_parameter_compatibility_output_preview/basic_preview/`
- `implementation_candidates/adapter_authored_parameter_compatibility_output_preview/`

## Validated Boundary

The fixture and implementation candidate validate an adapter-authored
compatibility output preview boundary:

- input authority is one approved parameter compatibility adapter request
  summary;
- the adapter output manifest must match request, approval, prepared-run
  context, measurement, parameter-state, adapter, and target-format identity;
- the target display must match the request target hint;
- target authority remains `adapter_declared`;
- Scopecat external file authority remains `not_claimed`;
- adapter-declared available targets require digest and positive size facts;
- adapter-declared unavailable targets require a reason;
- entries must account for every requested adapter key;
- emitted entries must preserve requested path, value, unit, and value shape;
- skipped entries require reasons and remain review findings;
- adapter findings can mark output ready-with-findings or blocked;
- no Scopecat output parsing, file write, file observation, hardware control,
  parameter write-back, external file authority, durable storage, GUI workflow,
  managed runner, or stable public adapter API is accepted.

The implementation candidate checks policy claims, request readiness,
request-to-manifest identity continuity, target facts, digest/size shape,
entry coverage, emitted-entry value continuity, skipped-entry reasons, and
adapter findings. The builder returns only the candidate summary, not fixture
status, reference-semantics, or decisions-not-earned text.

## What The Summary Can Answer

The candidate summary can answer:

- which adapter request and operator approval the output references;
- which prepared-run context, measurement, and selected parameter state are
  involved;
- which user-authored adapter and target format produced the declaration;
- which target facts the adapter declared;
- which entries were emitted or skipped;
- which adapter findings remain;
- why the result is a preview of adapter-declared facts, not Scopecat-owned
  compatibility output.

The expected-output fixture is an `internal_validation_summary` repository
artifact. This slice does not validate portable/export review artifact
behavior.

## Remaining Questions

- Should users record these artifacts through a generic debug/attachment route
  instead of compatibility-specific APIs?
- Should file observation wait until users need to audit a generated artifact
  independently of the selected parameter-state snapshot?
- Should any durable recording of derivative compatibility artifacts remain
  outside the parameter-state route until real workflow pressure demands it?

## Not Earned

This validation does not earn:

- Scopecat parsing of lab-specific output;
- compatibility file write;
- file observation or checksum verification;
- hardware control or current instrument state;
- parameter write-back;
- external file authority;
- durable storage;
- GUI behavior;
- managed runner behavior;
- stable public adapter API.

## Validation

- `uv run python -m unittest tests.test_adapter_authored_parameter_compatibility_output_preview_fixture tests.test_adapter_authored_parameter_compatibility_output_preview_summary_candidate`

## Slice Recommendation

Stop this slice as exploratory evidence. Do not add measurement-context links
or file-observation slices for compatibility output by default. The active
route should use the selected parameter-state snapshot as parameter context and
record derivative compatibility artifacts only as optional debug/attachment
evidence when explicitly supplied.
