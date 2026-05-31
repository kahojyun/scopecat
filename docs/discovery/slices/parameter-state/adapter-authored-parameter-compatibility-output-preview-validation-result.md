# Adapter-Authored Parameter Compatibility Output Preview Validation Result

## Status

Implementation candidate validated.

This is not an ADR, compatibility-output writer, adapter execution contract,
file-observation contract, hardware-control contract, parameter write-back
contract, durable storage contract, GUI design, managed runner, or stable
public adapter API.

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

- Should a later file-observation slice validate adapter-declared digest/size
  facts against an explicit external root?
- Should adapter-authored compatibility output become an input to measurement
  context links as a reference-only artifact?
- Should any durable recording of this preview wait until the measurement/run
  execution route is modeled?

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

Stop this slice at adapter-authored output preview. The next useful slice is
either explicit external file observation of adapter-declared output facts, or
a reference-only measurement context link that records the adapter-declared
compatibility output without importing or owning the external file.
