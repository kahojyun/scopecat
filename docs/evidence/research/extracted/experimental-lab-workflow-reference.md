# Experimental Lab Workflow Reference

## Status

Quarantined extracted reference. This is not product scope, a workflow map, a
scenario owner, a validation charter, or an architecture plan.

## Inputs

This note distills lab workflow patterns from current-owner clarification,
workflow improvement evidence, predecessor Fricon lessons, prompt-method
role-play, and external measurement-framework baseline review.

It deliberately avoids private sample paths and concrete local identifiers.

## Current Use

Use this file only as a background check when future product work risks missing
realistic lab workflow pressure. Prefer promoted owner docs first:

- stable evidence claims: [`../../inventory.md`](../../inventory.md)
- evidence interpretation rules: [`../../method.md`](../../method.md)
- failure packets: [`../../pain-packets/`](../../pain-packets/)
- adoption route hypotheses: [`../../../strategy/adoption-routes.md`](../../../strategy/adoption-routes.md)
- product boundaries: [`../../../strategy/vision.md`](../../../strategy/vision.md)

Do not infer product acceptance directly from this note. Promote only narrow
claims into owner documents after reference-case, interview, spike, or existing
evidence review.

## Promotion Map

| Workflow area | Current promoted owner |
| --- | --- |
| Existing artifact explanation and context ambiguity | EV-001, EV-002, EV-003, EV-006, EV-007 and relevant pain packets. |
| Selected-run analysis handoff | EV-009, EV-022, EV-039, EV-044, EV-045 and handoff route pressure. |
| Code/config readiness and dry-run packaging | EV-006, EV-007, EV-021, EV-025, EV-050 and code/readiness pressure. |
| Parameter memory and calibration decision evidence | EV-004, EV-005, EV-015, EV-038 and parameter/calibration pain packets. |
| Measurement-time read/monitor pressure and deferred advisory hypotheses | EV-046, EV-047 and running-run pain packet. |
| Setup reality and declared local schema | EV-041, EV-042, EV-043 and diagnostics/comparability packet. |
| Scientific comparison and known-good diagnostics | EV-030, EV-032, EV-036, EV-037, EV-041, EV-042 and diagnostics/comparability packet. |
| Derived analysis and claim lineage | EV-017, EV-018, EV-039 and analysis handoff packet. |
| Bounded local automation handoff | EV-024 and batch failure/review packet; still requires runtime-boundary evidence before execution scope. |

## Retained Workflow Lenses

These lenses help future reviewers check whether a candidate validation
question is too narrow. They are not a process sequence or implementation
order.

### Pre-Run Code And Context Staging

Relevant pressures:

- copied or archived experiment-code folders;
- ambiguous entrypoints, local paths, helper packages, and dependency readiness;
- selected user-code scope versus complete dependency closure;
- known-good references, machine-local profile, and restore/select-previous
  version questions.

Avoid promoting:

- automatic bidirectional sync;
- managed deployment;
- complete dependency closure;
- load-selected-version execution without a runtime decision.

### Setup And Bring-Up

Relevant pressures:

- wiring sheets, registry files, driver initialization, setup diagnostics, and
  local aliases;
- physical facts that software alone cannot prove;
- support packets that may need recipient-aware sharing boundaries.

Avoid promoting:

- authoritative setup truth;
- universal physical ontology;
- remote support agents or environment mutation.

### Calibration And Parameter Work

Relevant pressures:

- direct parameter writes, snapshots, registry drift, bad states, and working
  branches;
- fit quality, review pauses, retry/refit decisions, and downstream blocking;
- calibration dependency impact on later measurements, figures, and claims.

Avoid promoting:

- Scopecat-owned write-back;
- automatic rollback;
- proposal workflow or autonomous calibration without evidence.

### Measurement Campaigns

Relevant pressures:

- selected run ranges, scan semantics, generated protocols, run families, and
  partial recorded data;
- interruption, continuation, failure policy, review gates, and requested next
  action;
- read/monitor workflows that consume explicit records without taking over
  hardware control.

Avoid promoting:

- scheduler, queue, resource lease, or remote execution scope;
- passive scraping as the main live-observation model;
- automated advice before explicit recorded data proves useful.

### Analysis Handoff And Claims

Relevant pressures:

- moving selected high-value runs from control computer to analysis context;
- derived arrays, notebooks, corrections, exclusions, figures, spreadsheets,
  decks, and reports;
- source identity and impact review when calibration, code, setup, or analysis
  choices change.

Avoid promoting:

- report generator or publication workflow as first scope;
- semantic parsing of arbitrary binary or notebook payloads;
- a claim that full provenance must be complete before a handoff can be useful.

## Promotion Prompts

Before promoting a detail from this note, answer:

- What exact user failure or workaround does it explain?
- Which `EV-*` claims support it?
- Is it observed evidence, owner clarification, derived hypothesis, or
  low-confidence design pressure?
- Which pain packet or route owns the next durable statement?
- What smaller question can be answered before accepting architecture or
  execution scope?
- What would make this detail safe to delete from the research note?
