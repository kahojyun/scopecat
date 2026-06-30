# Diagnostics Catalog Contract

Status: accepted design baseline
Date: 2026-06-27

This note records the diagnostics catalog decisions that build on the earlier
accepted baselines. Diagnostics are already part of Scopecat's product surface:
tests assert diagnostic codes, dry runs expose diagnostics, boundary records
persist diagnostics, and domain packages emit their own domain diagnostics.

The accepted direction is to add a documented catalog and helpers around the
existing `Diagnostic` record. Do not replace diagnostic codes with a single
global enum, and do not make every domain package edit core files to introduce
domain-specific codes.

## Current Baseline

The current core diagnostic record is:

- `severity`: `info`, `warning`, `error`, or `blocker`;
- `code`: free-form string;
- `message`: human-readable text;
- `path`: optional logical source location.

Current code families are already tested across:

- workspace, experiment builder, run data, analysis, and candidate-config
  workflows;
- authoring and template resolution;
- parameter validation and candidate config review;
- experiment planning;
- storage, artifact, and manifest access;
- measurement dataset validation;
- analysis SDK surface and the internal automation SDKs it may wrap;
- reporting and run comparison;
- native execution and runner adapters;
- config registry activation and rollback;
- importer boundaries;
- lab-example readout analysis/reporting;
- virtual lab/native domain diagnostics.

The weakness is not the model shape. The weakness is that code ownership,
severity policy, and test helper conventions are implicit.

## Durable Contract

The durable diagnostics contract is:

- `Diagnostic` remains the shared record shape.
- Diagnostic codes are stable strings once asserted by public tests or
  persisted boundary records.
- Messages may improve, but tests should assert codes and structured paths
  rather than full prose unless prose is the contract.
- `path` is a logical model/artifact/expression location, not a local
  filesystem path.
- Severity has product meaning and should not be chosen ad hoc.
- Core and domain packages may own separate diagnostic namespaces.
- Catalog entries document code, owner, default severity, stability, and a
  short description.

The catalog is documentation plus optional test helpers first. It should become
runtime validation only after the code families stabilize enough to justify the
extra machinery.

## Catalog Entry Shape

Each catalog entry should record:

- code;
- owner package or subsystem;
- diagnostic family;
- default severity;
- stability level;
- short description;
- expected path shape;
- whether the code may appear in persisted records;
- related artifact/model family;
- replacement or deprecation note when applicable.

Recommended stability levels:

- `stable`: code is part of public/boundary behavior and should not change
  without updating docs and tests.
- `domain-stable`: code is stable inside an installed domain package.
- `internal`: code is useful for tests or developer feedback but not promised
  across package extraction.
- `deprecated`: code remains readable but should not be emitted by new paths.

## Severity Policy

Use severities consistently:

- `info`: non-blocking annotation, inferred source detail, or optional
  provenance note.
- `warning`: actionable issue that does not make the current artifact or run
  invalid.
- `error`: invalid input, missing required data, schema mismatch, failed step,
  or rejected operation that prevents the requested action.
- `blocker`: safety or policy stop that must prevent execution or activation
  before side effects.

Avoid `blocker` for ordinary validation failures. Use it when the system should
visibly distinguish "do not continue" from "this request failed."

## Namespace And Ownership

Core owns generic code families:

- `authoring_*`
- `experiment_*`
- `parameter_*`
- `proposal_*`
- `config_registry_*`
- `workspace_*`
- `data_*`
- `analysis_*`
- `candidate_config_*`
- `measurement_*`
- `artifact_*`
- `processing_*`
- `evaluation_*`
- `report_*`
- `run_comparison_*`
- `native_*`
- `runner_adapter_*`
- `import_*`
- `relation_*`
- `plan_preview_*`

Domain packages own domain-prefixed codes:

- `readout_*`
- `readout_iq_*`
- `virtual_lab_*`
- `lab_example_*`
- future package-specific prefixes such as `quantum_*` only after extraction
  decides the package name.

Domain packages should not emit generic core prefixes for domain-specific
semantics. Core should not emit domain-prefixed codes.

Test-only fake helpers may use clearly fake/test prefixes such as `test_*` or
`fake_*`; those should not enter production docs as stable product codes.

## Test Helper Direction

Tests should continue to assert exact codes when a behavior contract depends on
the failure mode. The next implementation cleanup should add catalog-aware test
helpers instead of replacing all assertions at once.

Accepted helper direction:

- assert that emitted codes are known to the relevant catalog namespace;
- assert default severity for stable codes when severity matters;
- assert code families without coupling tests to a full catalog file when the
  behavior only needs a family-level guarantee;
- keep direct string assertions for focused regression tests;
- avoid asserting diagnostic messages unless message wording is the product
  contract.

Good future helpers:

- `assert_diagnostic_code(diagnostic, "code")`
- `assert_diagnostic_family(diagnostic, "measurement")`
- `assert_known_diagnostic_codes(diagnostics, namespace="core")`
- `diagnostic_codes(diagnostics)` for compact comparisons

The existing `diagnostic_codes(...)` helper in experiment-kernel tests is a
good pattern for behavior-level comparisons. It should become shared only when
multiple suites need the same helper.

## Catalog Location

The first catalog should be a doc-backed source of truth:

- core catalog: `docs/diagnostics-catalog.md` or an equivalent generated table;
- domain catalog: package-local docs, for example under
  `examples/quantum/support`;
- tests may load a structured catalog later if the table becomes too large for
  manual review.

Do not create a runtime import cycle where every subsystem imports a central
constant module just to emit a diagnostic. Emission should stay local and
simple. Catalog validation can happen in tests.

## Relationship To Related Contracts

Storage and manifest:

- path escape, artifact missing, artifact kind mismatch, manifest schema, and
  selector validation codes are stable core families.

Measurement storage:

- schema mismatch, missing variable, unit mismatch, chunk gap/duplicate,
  incomplete artifact, and eligibility diagnostics should be cataloged.

Plan preview storage:

- preview truncation, preview artifact missing, preview schema mismatch, and
  preview row lookup failures should be cataloged before implementation.

Relation execution:

- unknown column, missing parameter, unsupported function, function argument
  mismatch, unsupported backend operation, and backend parity diagnostics
  should be cataloged before multiple backends land.

Calibration state:

- stale proposal, expected-value mismatch, candidate config stale, activation
  failure, rollback failure, missing evidence artifact, and proposal policy
  rejection should be cataloged.

Domain package extraction:

- package-owned diagnostics must carry package-owned prefixes and package-local
  catalog entries before extraction.

## Accepted Decisions

- Keep `Diagnostic` as the shared record shape.
- Keep diagnostic codes as strings, not a single global enum.
- Add catalog governance for stable code, owner, family, severity, path shape,
  and stability level.
- Core and domain packages own separate diagnostic namespaces.
- Catalog validation should start in tests and docs, not runtime emission.
- Tests should prefer code/path/severity assertions over message assertions.
- Test-only `fake_*` and `test_*` codes are not product catalog entries.

## Deferred Questions

- Whether the first catalog should be Markdown-only or a structured TOML/JSON
  file rendered into docs.
- Whether public APIs should expose catalog lookup helpers.
- Whether stable diagnostic codes should become typed constants for core only.
- Which existing direct string assertions should migrate first.
- Whether severity defaults should be enforced automatically in tests.
- How to version domain package diagnostic catalogs after extraction.
