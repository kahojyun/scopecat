# Approved Parameter Compatibility Adapter Request Validation Plan

## Status

Validation plan, not an ADR.

This plan defines the adapter-mediated boundary for compatibility output after
operator approval. It does not accept adapter execution, compatibility output
production, file writes, hardware control, parameter write-back, external file
authority, dependency operations, fresh reads, durable storage, GUI behavior,
managed runner behavior, or a stable public adapter API.

## Source Material

This slice follows:

- [`prepared-run-operator-pre-run-approval-validation-result.md`](prepared-run-operator-pre-run-approval-validation-result.md)
- [`parameter-write-compatibility-output-validation-result.md`](parameter-write-compatibility-output-validation-result.md)
- [`adapter-authored-parameter-state-import-preview-validation-result.md`](adapter-authored-parameter-state-import-preview-validation-result.md)

The import route already treats user-owned adapters as the authority for
legacy-source parsing. Compatibility output has the same pressure in reverse:
Scopecat should prepare reviewed parameter facts for an external adapter, but
the lab-specific external output format should be authored by user adapter
code.

First fixture:

- `tests/fixtures/approved_parameter_compatibility_adapter_request/basic_request/`

## Validation Question

Can Scopecat prepare an adapter input request from an approved parameter-state
review without executing the adapter, writing the compatibility file, or
claiming authority over the external file format?

## First Fixture Shape

The first fixture should include:

- one operator pre-run approval summary with
  `operator_pre_run_review_approved`;
- one user-authored external adapter profile;
- one adapter request bound to the approved prepared-run context, measurement,
  approval, and parameter-state snapshot;
- scalar trusted parameter entries to provide to the adapter;
- a target hint whose path authority remains adapter/user owned and whose
  display identity is public-safe and redacted.

The fixture should not include:

- adapter process execution;
- compatibility file output;
- filesystem writes or durable storage;
- hardware state, hardware write-back, or instrument logs;
- final public adapter API;
- GUI operations.

## Expected Output

Expected request output should let a reviewer answer:

- which approved operator decision authorized the adapter request;
- which prepared-run context, measurement, and parameter-state snapshot are
  being prepared for adapter use;
- which user-authored adapter profile is targeted;
- which scalar trusted entries are being requested;
- why the request does not execute the adapter, write files, produce
  compatibility output, control hardware, or claim external file authority.

## Out Of Scope

This plan does not earn:

- adapter execution;
- compatibility output production;
- file write or durable storage;
- hardware control or current instrument state;
- parameter write-back;
- external file authority;
- dependency resolution, sync, package installation, or runtime probing;
- fresh storage or workspace observation;
- GUI behavior;
- managed runner behavior;
- stable public adapter API.
