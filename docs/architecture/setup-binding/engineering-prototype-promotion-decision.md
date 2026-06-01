# Setup Binding Engineering Prototype Promotion Decision

## Status

Accepted narrow promotion.

## Decision

Promote the validated setup-binding candidate into a route-local engineering
prototype under `scopecat.setup_binding`.

The promoted surface is intentionally narrow:

- explicit station registry context references with redacted connection
  payload posture;
- explicit setup-binding snapshots for sample/cooldown/session-specific
  logical-to-physical binding context;
- declared logical binding summaries and generated line/readout views;
- measurement run-start input references to parameter state, setup binding,
  and station registry context;
- simple binding diffs and review attention for changed bindings.

The accepted chain is:

```text
explicit station registry context
  -> explicit setup-binding snapshots
  -> declared generated line/readout views
  -> measurement run-start input references
  -> local review summary and attention findings
```

This promotion keeps setup binding as a side-effect-free review projection. It
does not inspect hardware, execute project generator/converter code, interpret
opaque project payloads, mutate parameter state, write hardware setup, decide
parameter invalidation, define station-registry truth, infer a wiring ontology,
start runs, or define a shared input-snapshot schema.

## Boundary

The promoted output is a local `review_summary` / local review projection. It
is not a portable/public/export artifact.

Repository fixtures remain repository-safe validation fixtures. Runtime
redaction is not added at this boundary because the promoted surface does not
produce portable handoff, package, or public documentation artifacts. The live
implementation still validates public-safe managed references and rejects
connection-payload, generator-execution, and hardware-state claims where the
setup-binding boundary owns those facts.

## Rationale

Setup binding has a stable side-effect-free candidate boundary and a clear
workflow gap between parameter state, station registry context, and hardware
control. Promoting the narrow surface lets later measurement-context,
prepared-run, and selected-reference work consume explicit setup context
without turning Scopecat into a station manager, generator runner, hardware
controller, or universal run-context model.

## Engineering Coverage

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Setup-binding summary | Promoted into route-local engineering code with typed request/result objects and a raw-dictionary adapter only at the fixture/current-caller edge. | [`scopecat/setup_binding/README.md`](../../../scopecat/setup_binding/README.md), this decision |
| Measurement run-start setup context | Promoted only for explicit measurement input references that name parameter state, setup binding, and station registry context in this setup-binding surface. It does not define a shared input-snapshot framework. | [`scopecat/setup_binding/README.md`](../../../scopecat/setup_binding/README.md), this decision |
| Station registry context | Referenced as redacted declared context only. Station registry schema, connection payloads, station management, and current hardware state remain outside this module. | [`setup-binding.md`](../../discovery/problem-briefs/setup-binding.md) |

## Next Decision Gate

Do not continue by promoting a full setup/station platform. Future work should
choose one explicit authority change:

- setup-binding storage/read behavior;
- prepared-run or selected-reference consumption of setup-binding summaries;
- station-registry schema and management behavior;
- project-authored generator/converter execution;
- user/project-defined inner payload import/export semantics;
- hardware setup truth or hardware-control integration;
- GUI or notebook setup-binding switch/review presentation.

Each path needs its own non-claims before it can add storage mutation,
generator execution, payload interpretation, hardware truth, hardware control,
or shared context schemas.
