# Measurement Context Workflow Review Strategy

## Status

Discovery synthesis, not an ADR.

This note explains how to review the accumulated measurement-context discovery
slices. It is a product/workflow review aid, not an accepted storage model,
GUI contract, execution framework, or universal context schema.

## Review Question

Review these slices first for workflow fidelity:

Do they model how a lab user can gradually move an existing experiment workflow
into Scopecat without making context adoption, review findings, or artifact
management mandatory?

Implementation details matter after that question is answered. Most slices are
validation candidates over fixtures, so the largest risk is an incorrect
workflow model rather than Python mechanics.

## Migration Ladder

Scopecat should support partial adoption. A user should be able to start with
opaque review material around legacy scripts, then adopt managed context only
where it removes real ambiguity.

```mermaid
flowchart LR
  L0["Legacy-first\nattachments, notes,\nopaque snapshots"]
  L1["Reference-first\nselected context links\nwithout payload ownership"]
  L2["Managed parameter state\nsnapshots, lineage,\ntrust/current facts"]
  L3["Setup binding\nsetup, station,\nreadout context"]
  L4["Experiment code context\nmanaged code version,\nworkspace, environment"]
  L5["Review composition\nintent, record, evidence,\nprovenance, observation"]

  L0 --> L1 --> L2 --> L3 --> L4 --> L5
```

Early users may only use Scopecat as a structured review notebook. Later users
may choose managed parameter state, setup binding, code context, or richer
artifact provenance. Measurement-record validity should not depend on adopting
all of these routes.

## Experiment Flow

The validated slices should be read as optional layers around an experiment:

```mermaid
flowchart TD
  A["Existing lab workflow"] --> B["Prepare run or calibration step"]
  B --> C{"Context adopted for this route?"}

  C --> C0["No\nattach notes, logs,\nopaque snapshots"]
  C --> C1["Partially\nreference-only context links"]
  C --> C2["Yes\nmanaged parameter/setup/code records"]

  C0 --> R["Run experiment"]
  C1 --> R
  C2 --> R

  R --> RR["Running record state"]
  RR --> E["During-run supporting evidence"]
  E --> PR["Post-run local review"]
  PR --> AP["Optional artifact provenance"]
  AP --> AO["Optional artifact observation"]
  AO --> N["Next run, rerun, calibration follow-up,\nor no action"]
```

Context, supporting evidence, artifact provenance, and artifact observation are
separate layers. A workflow may use any subset.

## Passive Review By Default

Most review slices are display/state projections. They should make system
state legible in a GUI, CLI, or notebook, not interrupt an experiment by
default.

```mermaid
flowchart LR
  F["Finding / attention / review state"] --> V["Visible review surface"]
  V --> U["User may inspect or ignore"]
  U --> A["Optional action"]

  F -.not by default.-> G["Approval gate"]
  F -.not by default.-> B["Run blocker"]
  F -.not by default.-> M["Measurement invalidation"]
  F -.not by default.-> W["Storage mutation"]
```

Reserve `approval` and `gate` for slices backed by an explicit local
policy/template that provides interruption semantics. Passive GUI/review state
should use `review`, `attention`, `finding`, `status`, or `incomplete`.
`required` and `blocked` should be scoped to the local review surface, such as
`blocked_for_context_review`; they do not mean that hardware execution or
measurement validity has been decided.

## Boundary Rules

- Measurement context is optional for primary measurement-record validity
  unless a narrower workflow explicitly earns stronger semantics.
- Measurement intent may carry moving selectors; measurement records carry the
  resolved snapshot links actually used.
- Supporting evidence is not canonical context by default.
- Attachments and debug logs are opaque supporting evidence unless a later
  accepted slice promotes a specific artifact family into context.
- Artifact provenance is optional and declared; it does not prove complete
  analysis lineage.
- Artifact observation is file-level only; it does not parse payloads, generate
  previews, or decide artifact correctness.
- Context readiness is local review state; it is not runnable readiness,
  hardware safety, setup truth, or run blocking.
- Calibration review slices should be checked against real notebook workflows
  before treating their child-summary chain as required product shape.

## Review Checklist

Use this order for branch review:

1. Confirm the migration ladder matches real lab adoption behavior.
2. Confirm review states are passive visibility by default.
3. Confirm optional context stays optional for measurement-record validity.
4. Confirm intent/record boundaries preserve moving selectors versus resolved
   snapshots.
5. Confirm supporting evidence, artifact provenance, and artifact observation
   remain separate from canonical context and storage.
6. Confirm calibration slices do not over-require a complete linear workflow
   when real users may have partial notebook outputs.
7. Only then review implementation mechanics, fixture coverage, and schema
   strictness.

## Workflow Questions To Resolve

- Which local policies or templates, if any, turn review findings into
  mandatory gates?
- Are opaque snapshots initially only supporting evidence, or is there a weak
  context-record envelope users expect early?
- Which artifact types actually need provenance and file-level observation in
  normal review?
- Does calibration acceptance mean external apply, parameter-state handoff, or
  two distinct states?
- Should post-run artifact observation coverage ever be required, or only
  surfaced when provided?
