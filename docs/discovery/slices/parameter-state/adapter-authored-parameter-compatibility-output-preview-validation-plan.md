# Adapter-Authored Parameter Compatibility Output Preview Validation Plan

## Status

Validation plan, not an ADR.

This plan defines the adapter-to-Scopecat return boundary for compatibility
output. It does not accept Scopecat parsing of lab-specific output payloads,
file writes, file observation, hardware control, parameter write-back, external
file authority, durable storage, GUI behavior, managed runner behavior, or a
stable public adapter API.

## Source Material

This slice follows:

- [`approved-parameter-compatibility-adapter-request-validation-result.md`](approved-parameter-compatibility-adapter-request-validation-result.md)
- [`adapter-authored-parameter-state-import-preview-validation-result.md`](adapter-authored-parameter-state-import-preview-validation-result.md)
- [`parameter-write-compatibility-output-validation-result.md`](parameter-write-compatibility-output-validation-result.md)

The prior request slice prepares approved Scopecat parameter facts for a
user-authored adapter. This slice validates the reverse handoff: the adapter
declares what compatibility output it produced or skipped, and Scopecat checks
identity continuity and review facts without owning the external format.

First fixture:

- `tests/fixtures/adapter_authored_parameter_compatibility_output_preview/basic_preview/`

## Validation Question

Can Scopecat validate an adapter-authored compatibility output manifest against
the approved adapter request without parsing, writing, or observing the
lab-specific output file?

## First Fixture Shape

The first fixture should include:

- one approved parameter compatibility adapter request summary;
- one adapter-authored output manifest with request, approval, prepared-run
  context, measurement, parameter-state, adapter, and target identities;
- adapter-declared target display, reference state, digest, and size facts;
- adapter-declared emitted entries matching every requested adapter key;
- adapter findings as review facts.

The fixture should not include:

- Scopecat parsing of the external output format;
- filesystem writes or observation;
- hardware state, hardware control, or parameter write-back;
- durable storage mutation;
- GUI interaction contracts;
- stable public adapter API.

## Expected Output

Expected preview output should let a reviewer answer:

- which adapter request and operator approval the output references;
- which prepared-run context, measurement, and parameter state are involved;
- which user-authored adapter and target format produced the declaration;
- which external target facts the adapter declared;
- which requested entries were emitted or skipped;
- which adapter findings remain;
- why Scopecat has not parsed, observed, written, stored, or applied anything.

## Out Of Scope

This plan does not earn:

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
