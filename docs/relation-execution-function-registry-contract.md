# Relation Execution And Function Registry Contract

Status: accepted design baseline
Date: 2026-06-27

This note records the relation execution and function registry decisions that
build on
[PlanSnapshot Preview Storage Contract](plan-snapshot-preview-storage-contract.md).
It defines how Scopecat can scale relation planning and add pure functions
without making a dataframe engine, Python callback, or domain package part of
the durable expression contract.

The current implementation intentionally keeps `scopecat.relations` small:
durable relation and scalar expression records, parameter lookup, quantity
arithmetic, boolean/comparison operators, and a deterministic local evaluator.
That remains the baseline.

## Current Baseline

The current durable relation model includes:

- scalar expression kinds: literal, column, outer column, parameter scalar,
  parameter lookup, binary operator, and case;
- scalar operators: arithmetic, comparison, boolean `and`, and boolean `or`;
- series expressions: values, linspace, and range;
- relation roots: literal rows, parameter table, and grid;
- relation operations: select, filter, join, cross, with columns, sort, and
  limit;
- deterministic local evaluation for tests, dry-run previews, parameter
  derivations, parameter patch planning, desired-state planning, and repeated
  state bindings.

There is no function-call expression kind and no function registry today.
Existing docs mention selected pure functions such as unit conversion and power
conversion, but those functions are not yet a durable production contract.

## Durable Contract

The durable relation contract is:

- `RelationExpr`, `ScalarExpr`, `SeriesExpr`, and related records remain
  serializable Pydantic records.
- A relation expression cannot embed Python callbacks, lambdas, dataframe
  expressions, backend-specific query strings, or domain-package classes.
- Execution backends may change, but every backend must implement the same
  durable IR semantics and diagnostics.
- Function extensibility must use stable function ids in durable expression
  records.
- Domain packages may register additional pure functions, but registration
  changes evaluator capability, not the serialized shape of expressions.
- Relation outputs used for plan review materialize through the preview
  storage contract, not through backend-native table objects.

## Core Function Set

Core should keep the function set deliberately small. The accepted core set is:

- unit conversion for compatible `Quantity` values;
- numeric power conversion helpers that are domain-neutral, such as linear to
  dB and dB to linear;
- numeric clamp/min/max only if planning use cases require them;
- string or id formatting only when it is deterministic and locale-free.

Do not add domain-shaped functions to core, including quantum, pulse, readout,
waveform, classifier, hardware-sweep, active-reset, or calibration-model
helpers.

The first implementation should add a `function` scalar expression kind only
when a real accepted use case needs it. That expression should contain:

- stable function id;
- ordered or named argument expressions;
- optional keyword arguments if all values are scalar expressions or literals;
- optional expected return type metadata for validation and diagnostics.

Function ids should be plain strings with namespaces, for example:

- `scopecat.quantity.to_unit`
- `scopecat.numeric.db_to_linear`
- `scopecat.numeric.linear_to_db`
- `lab_example.readout.some_domain_function`

## Function Registry

The function registry should be an execution capability registry, not a new
serialization layer.

Each registered function should declare:

- function id;
- package or owner;
- semantic version or compatibility marker;
- deterministic/pure flag, initially required to be true;
- argument contract;
- return contract;
- supported evaluator backends;
- diagnostic code prefix or diagnostic family;
- optional documentation string.

Registration should happen through explicit APIs in the package that owns the
function. Importing a domain package may make functions available to a session,
but durable expressions must still carry only function ids and arguments.

Unregistered functions are validation errors. They should not fall back to
dynamic imports, `eval`, or runtime name lookup.

## Execution Backends

The local evaluator remains the reference backend for:

- small plans;
- tests;
- dry-run previews;
- deterministic validation;
- environments without optional dataframe dependencies.

A future vectorized backend such as Polars may be added for large planning and
preview generation, but it is an implementation detail. It must:

- accept the same durable relation records;
- preserve point order where the IR requires order;
- emit the same diagnostic codes for validation failures;
- refuse unsupported functions explicitly;
- materialize preview outputs through typed preview artifacts;
- avoid leaking backend-specific expression objects into public APIs or stored
  records.

Backend selection should be a planner/execution option and should be recorded
in plan provenance when it can affect performance or diagnostics. It must not
change plan content semantics.

## Module Ownership

Keep `scopecat.relations` focused on durable IR and small local evaluation.

Accepted module direction:

- `scopecat.relations`: public durable records, small helper constructors, and
  reference local evaluation entry points.
- private relation scalar/evaluator modules: path reading, arithmetic,
  comparison, local evaluation helpers, and backend adapters.
- future expression/function module, if needed: registry models and validation
  helpers once functions become a real contract.
- domain packages: domain function registration and tests for their own
  function semantics.

Do not move relation records into a backend-specific module. Do not add
compatibility alias modules for old expression paths.

## Diagnostics

Relation diagnostics should stabilize before multiple backends are introduced.
The accepted diagnostic families are:

- unknown column or unreadable path;
- unknown parameter scalar;
- unknown parameter table;
- ambiguous or missing parameter lookup row;
- unsupported relation operation;
- unsupported scalar expression kind;
- unsupported function id;
- function argument mismatch;
- function return type mismatch;
- backend unsupported operation;
- backend result mismatch during parity tests.

Where possible, evaluator exceptions should be converted into structured
diagnostics at planning boundaries. The low-level evaluator may still raise
ordinary Python errors internally, but user-facing dry-run, planner, and
preview APIs should report stable diagnostic codes and logical expression
paths.

## Relationship To Related Contracts

Plan preview storage:

- Large relation outputs should materialize as point or planner preview
  artifacts.
- A backend-native relation table is never the durable preview format.

Measurement storage:

- Relation execution creates plan rows and parameter views. Measurement
  storage begins only after acquisition or processing creates measurement
  artifacts.

Calibration state:

- Calibration-specific fit and model functions belong in a domain package or a
  later calibration-state contract until a stable core need exists.

Diagnostics catalog:

- Relation diagnostics are strong candidates for the future diagnostics
  catalog because they are shared by authoring, parameter derivations,
  planning, previews, and domain packages.

## Accepted Decisions

- The current deterministic local evaluator remains the reference backend.
- Durable relation records must not contain Python callbacks or backend-native
  expressions.
- Function extensibility should use stable function ids plus a registry, not
  serialized code.
- Domain packages may register pure functions without changing durable
  expression record shape.
- Core function scope stays domain-neutral and minimal.
- Future vectorized execution engines are implementation details behind typed
  relation records and preview artifacts.
- Relation diagnostics should stabilize before adding multiple execution
  backends.

## Deferred Questions

- Exact schema shape for a future scalar `function` expression.
- Whether function ids should use reverse-DNS, package names, or another
  namespace convention.
- Whether registry entries should be persisted into `PlanSnapshot` provenance
  or only recorded as planner implementation metadata.
- Which optional vectorized backend should be attempted first.
- Whether backend parity tests should be required for every registered
  function or only for core functions.
- Whether function registry helpers belong in `scopecat.relations` or a future
  `scopecat.expressions` module.
