# Calibration Parameter-State Intake Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow parameter-state slice for consuming an accepted
calibration write handoff through explicit parameter-state review. It does not
accept final parameter-state schema, storage mutation, durable history,
compatibility output, hardware write-back, rollback, calibration execution,
GUI behavior, or shared domain model extraction.

## Source Material

This slice follows two validated boundaries:

- [`../calibration/calibration-accepted-write-handoff-validation-result.md`](../calibration/calibration-accepted-write-handoff-validation-result.md)
- [`adapter-parameter-import-review-commit-validation-result.md`](adapter-parameter-import-review-commit-validation-result.md)

The calibration handoff slice validated that calibration can shape an accepted
proposed write as a parameter-state route request without creating drafts,
committed states, compatibility output, or hardware apply. This slice tests
the next owner boundary: parameter-state management consumes that handoff after
explicit review and projects a managed parameter-state summary.

First fixture:

- `tests/fixtures/calibration_parameter_state_intake/basic_intake/`

## Validation Question

Can parameter-state management consume a validated calibration accepted-write
handoff as explicit reviewed input, apply the handoff diff to a base
parameter-state summary, and preserve calibration evidence as provenance while
avoiding storage mutation, durable history writes, compatibility output,
hardware write-back, rollback, and calibration execution?

## Evidence Pressure

The validated calibration continuation slices show that calibration can produce
reviewable proposed writes and accepted handoff requests. The upstream
parameter-state stack now validates review/commit-shaped managed state,
storage writer/read view, prepared-run consumption, and review gates. The
remaining pressure is the narrow intake seam between those owner routes.

This fixture intentionally keeps the bridge small:

- one accepted calibration handoff request;
- one parameter-state intake review acceptance;
- one changed scalar parameter entry;
- one carried-forward base parameter entry;
- calibration step, observation, write, and handoff identities preserved as
  provenance;
- no storage write, compatibility file, hardware apply, rollback, or scheduler
  behavior.

## First Fixture Shape

The first fixture should include:

- a nested calibration accepted-write handoff input;
- parameter-state intake review identity, status, accepted time, reviewer role,
  handoff id, source handoff review id, and accepted diff paths;
- managed parameter-state identity, lineage, base state, source handoff,
  review id, readiness, trust status, trusted paths, changed entries, and
  carried-forward entries;
- explicit side-effect claims.

The fixture should not include:

- storage paths or write receipts;
- external compatibility output;
- hardware state, hardware writes, or instrument logs;
- rollback instructions;
- calibration or measurement payload execution;
- GUI operations.

## Expected Output

Expected review output should let a reviewer answer:

- which calibration handoff was consumed;
- which handoff diff paths parameter-state review accepted;
- which managed parameter-state summary resulted;
- which entries changed and which were carried forward;
- which calibration step, measurement observation link, proposed write, and
  base state provide provenance;
- why no storage, durable history, compatibility output, hardware write-back,
  rollback, or calibration execution occurred.

## Out Of Scope

This plan does not earn:

- final parameter-state schema;
- storage mutation or durable history;
- compatibility output;
- hardware write-back or current instrument state;
- rollback contract;
- calibration or measurement execution;
- shared relation graph;
- GUI behavior;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at side-effect-free parameter-state intake summary. Use the
existing parameter-state storage writer when a later workflow needs bounded
local storage, and keep compatibility output or hardware apply as separate
post-commit concerns.
