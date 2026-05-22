# Setup Binding Validation Result

## Status

Fixture-level validation result, not an ADR.

This result records what the first setup-binding fixture proved and where the
boundary remains intentionally narrow.

## Fixture

- `tests/fixtures/setup_binding/basic_binding_context/`

The fixture validates a first setup-binding boundary:

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

Here, selection is the run-start action that chooses a setup-binding snapshot
version. It is not a separate durable concept from the setup-binding snapshot
itself. This matches the cross-slice vocabulary in
[`cross-slice-synthesis.md`](cross-slice-synthesis.md): parameter states and
code versions face similar point-in-time context pressure, even though each
family keeps its own lifecycle, diff, storage, and restore semantics.

## What Changed

The fixture makes the measurement-context direction more explicit. Instead of
using one-off fields for each selected state, it uses:

```json
"inputs": [
  {"name": "parameter_state", "snapshot_id": "param-state-0002"},
  {"name": "setup_binding", "snapshot_id": "setup-binding-0002"},
  {"name": "station_registry", "snapshot_id": "station-registry-mmcs2-redacted"}
]
```

This shape is useful future pressure, but it does not earn a universal
snapshot framework. Each snapshot family still needs its own meaning.

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
validating them.

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
- many-snapshot measurement context may become useful, but shared extraction
  is still deferred until implementation pressure justifies it.

## Current Recommendation

Stop setup binding at fixture validation for now unless the next design step
needs a production-shaped summary candidate. Use the fixture when evaluating
measurement run-context design, parameter-state selection, selected-reference
comparison, and future station-registry boundaries.
