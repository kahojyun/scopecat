# Setup Binding Validation Result

## Status

Implementation candidate validation result, not an ADR.

This result records what the first setup-binding fixture proved and where the
production-shaped summary boundary remains intentionally narrow.

Artifact posture: `internal_validation_summary`. This validation result, its
fixture inputs, and expected output are repository-safe discovery artifacts,
not portable/public export artifacts.

## Fixture

- `tests/fixtures/setup_binding/basic_binding_context/`

The fixture and implementation candidate validate a first setup-binding
boundary:

- station registry can be referenced as separate redacted station context;
- setup binding can be represented as a sample/cooldown/session-specific
  snapshot;
- a measurement can record run-start context as a list of named input
  snapshots;
- parameter state, setup binding, and station registry can appear in that list
  without sharing lifecycle, diff, review, or authority semantics;
- setup-binding snapshots can allow user/project-defined inner payloads while
  Scopecat starts from an outer envelope and declared summaries;
- generated line/readout views can be carried as binding context without
  executing or validating project generator/converter code;
- a binding diff can mark attention-worthy changes without automatically
  invalidating parameter state.

The implementation candidate lives in
`implementation_candidates/setup_binding/`. It builds the same structured
candidate summary from explicit fixture input and validates the fixture-local
reference boundary before producing output.

Here, selection is the run-start action that chooses a setup-binding snapshot
version. It is not a separate durable concept from the setup-binding snapshot
itself. This matches the cross-slice vocabulary in
[`synthesis/cross-slice.md`](../../synthesis/cross-slice.md): parameter states and
code versions face similar point-in-time context pressure, even though each
family keeps its own lifecycle, diff, storage, and restore semantics.

## What Changed

The fixture makes the measurement-context direction more explicit. Instead of
using one-off fields for each selected state, it uses:

```json
"inputs": [
  {"name": "parameter_state", "snapshot_id": "param-state-0002"},
  {"name": "setup_binding", "snapshot_id": "setup-binding-0002"},
  {"name": "station_registry", "snapshot_id": "station-registry-synthetic-redacted"}
]
```

This shape is useful future pressure, but it does not earn a universal
snapshot framework or a global requirement that every measurement provide all
three inputs. The fixture chooses parameter state, setup binding, and station
registry together because that is the setup-binding pressure being validated.
Each snapshot family still needs its own meaning, and setup binding should be
reviewable as its own context family.

## Implementation Candidate

The candidate builder is side-effect free. It validates and summarizes:

- redacted station-registry context references, resource identity membership,
  and resource counts;
- setup-binding snapshots with sample, cooldown, session, selected registry,
  declared logical bindings, and declared generated views;
- user/project-defined inner payload policy, kept opaque by default;
- project generator references only when they explicitly do not claim
  execution;
- measurement input references to parameter state, setup binding, and station
  registry snapshots;
- measurement runtime context references to declared generated views;
- simple binding diffs and review attention for changed bindings.

It rejects fixture inputs that claim current hardware state, generator
execution, station-registry connection payloads, missing registry resources,
unknown selected snapshots, unknown generated views, or non-opaque inner
payload handling.

## Boundary Confirmed

Setup binding remains separate from:

- parameter state, which owns calibrated values, lineage, readiness, trust, and
  review history;
- station registry, which owns station/lab configuration context;
- hardware control, which owns execution and instrument behavior;
- project generator/converter code, which is black-box provenance in this
  slice.

Generated `line_info` and readout-group views are included because real setup
binding often appears through generated runtime artifacts. The fixture records
their labels and consumer hints, not a product contract for rendering or
validating them. If a generated view depends on both setup binding and
parameter/runtime context, this slice treats that view as declared binding
context for review only. A later slice should decide whether such mixed
generated views are setup-binding context, runtime context, or supporting
evidence.

The fixture also clarifies inner payload handling. A setup-binding snapshot may
contain a user/project-defined payload needed by downstream runtime code.
Scopecat does not need to deeply interpret that payload in the first boundary.
It owns the outer envelope: snapshot identity, provenance, selected registry
context, measurement input references, declared summary fields, simple diffs,
and attention metadata.

## Remaining Risks

- the final setup-binding schema is still undecided;
- user/project-defined inner payload import/export behavior is still
  undecided;
- the station registry boundary may need a later slice if Scopecat moves
  toward station management;
- setup-binding diffs are currently simple role-to-resource changes, not a
  full wiring ontology;
- parameter invalidation remains a domain/user decision, not an automatic
  consequence of binding changes;
- whether real setup-binding review is usually independent, or usually shown
  alongside selected parameter state and station-registry context, remains a
  product workflow question;
- many-snapshot measurement context may become useful, but shared extraction
  is still deferred until implementation pressure justifies it.

## Slice Recommendation

Keep setup binding at this slice-local implementation candidate until another
task needs stronger authority. Use the candidate when evaluating measurement
run-context design, parameter-state selection, selected-reference comparison,
and future station-registry boundaries.

Do not extract a shared snapshot framework, station registry schema, setup
truth model, generator contract, hardware-control contract, GUI workflow, or
payload interpreter from this result.
