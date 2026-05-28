# Calibration Work Continuation Validation Result

## Status

Fixture validation result with tiny assembler candidate.

This is not an ADR, final workflow model, runner framework, scheduler design,
authoring DSL, dependency graph, dataflow model, GUI design, storage schema,
parameter schema, retry policy, write-back policy, remote-execution design,
resource-arbitration decision, or hardware-control decision. It records what
the current calibration-continuation fixture proved and where the boundary
should remain narrow.

## Inputs

- [`problem-briefs/calibration-work-continuation.md`](../../problem-briefs/calibration-work-continuation.md)
- [`calibration-work-continuation-validation-plan.md`](calibration-work-continuation-validation-plan.md)
- `tests/fixtures/calibration_work_continuation/review_gate_failed_fit/`
- `implementation_candidates/calibration_work_continuation/`

## Validated Boundary

The fixture validates a first boundary for calibration continuation as
continuation-state assembly, not runner-log replay.

That boundary is a deliberate tradeoff:

- within this fixture, it is structured enough to answer what happened, what is
  blocked, what manual choices are visible, and what was not written;
- it is less uncertain than designing an executor input, dependency graph,
  scheduling policy, retry model, or dataflow language;
- within this fixture, it is more organized than raw record storage because it
  collects scattered context into a resume-oriented summary;
- it keeps executor pressure visible without accepting executor ownership.

The input fixture now represents scattered continuation context:

- declared calibration intent;
- declared step plan;
- observed measurement records;
- observed parameter snapshots;
- observed fit preview;
- proposed write from user-authored code;
- operator note;
- known review state;
- known blocking state.

The expected summary organizes that context into:

- episode state;
- step lifecycle state;
- outputs;
- review gates;
- declared writes;
- applied writes;
- requested next actions;
- attention-worthy warnings.

## Important Separations

The fixture clarified several boundaries that should be preserved:

- `declared_step_plan` is interpretive context for this fixture, not a final
  authoring model or executor input contract.
- Step lifecycle state is assembled from observed records, known review state,
  and known blocking state; it is not treated as a supplied runner log.
- Planned context and observed context need distinct provenance. The expected
  summary separates `plan_source`, `lifecycle_source`, and observed output
  `authority`.
- Proposed writes and applied writes are separate. A user-authored proposed
  write is not a Scopecat-decided mutation.
- Review-needed and blocked states are ordinary calibration-continuation state.
  Warnings explain attention-worthy consequences such as failed fit quality,
  blocked downstream steps, or write review requirements.
- Requested next actions are manual choices, not an automatic continuation
  plan.

## Assembler Candidate

The tiny implementation candidate checks that the current read model can be
produced mechanically from scattered fixture context without silently inventing
missing references.

It assembles and validates references for:

- step lifecycle state from observed records, known review state, and known
  blocking state;
- output summaries from observed measurements, parameter snapshots, and fit
  previews;
- review gates from known review state and related records;
- declared writes from proposed writes produced by user-authored code;
- fixture-specific manual choices implied by requested decisions and known
  blocking state;
- attention warnings from failed fit quality, blocked downstream steps, and
  proposed-but-not-applied writes.

The assembler does not prove product usefulness by itself. It shows that the
fixture's continuation context can be reshaped into a coherent review summary,
with basic referential integrity checks around review reasons, blocking
references, proposed-write evidence sources, and applied-write records.

The builder remains side-effect free. It does not execute calibration code, read
source data, inspect notebooks, discover files, fit data, apply writes, retry
steps, schedule work, or control hardware.

## What The Fixture Can Answer

The current summary can answer:

- which calibration episode was being continued;
- which steps were planned and which target they concerned;
- which step completed;
- which step needs review;
- which step is blocked and why;
- which measurements, fit previews, and parameter snapshots exist;
- whether fit quality failed the fixture-declared threshold;
- which parameter write was proposed;
- that no write was applied;
- which manual choices are available: review fit, accept outside Scopecat after
  review, rerun the Rabi step, skip the target, or wait because T1 is blocked.

## Domain Review Result

The current summary appears close enough for the near-term purpose: it contains
the continuation information needed for a future smoother resume experience,
such as a GUI that lists unresolved items and lets a user resolve them one by
one. The fixture does not validate that GUI experience itself.

The proposed-write framing is directionally right: user-authored calibration
code can propose a parameter value, while Scopecat records that proposal and
does not apply it. This points to a likely Scopecat capability, but not yet a
write-back contract: Scopecat may need to record and summarize proposals even
when parameter snapshots, calibration code, and final parameter authority remain
externally managed.

Blocked-cause traceability is useful, but it should not become the primary user
surface if the system is reliable. Users should normally care about current
available operations or needed interventions; detailed blocked reasons remain
supporting context for review, debugging, or trust.

The early-adoption framing should assume that users may still manage snapshots,
calibration scripts, and some continuation context outside Scopecat. A next
fixture should not require mature Scopecat ownership of every calibration step
unless that is the explicit question under validation.

Product-facing language should move away from raw "manual choices" over time
toward intervention or operation language: actions that require user attention,
available resume operations, and unresolved items. Complex interventions such
as changing experiment definitions or fixing calibration code remain outside
the current boundary.

## Still Not Earned

This validation does not earn:

- local executor implementation;
- runner framework;
- final authoring model or executor input contract;
- dependency graph, dataflow model, mutual-exclusion model, or scheduling
  policy;
- automatic retry, optimization, or retune;
- Scopecat-decided parameter mutation or write-back;
- rollback semantics;
- final parameter schema;
- fit quality validation or user/domain scientific conclusions;
- GUI implementation;
- generic episode/step/review model;
- hardware control or resource arbitration.

Calibration remains the concrete workflow under validation. A more general
episode, step, review, output, parameter, write, or continuation model is not
earned until another slice pressures the same concepts.

## Remaining Risks

- The fixture is hand-authored. It validates fixture shape and summary boundary,
  while the assembler validates only the current single fixture shape.
- The fixture covers one review-gate failure and one blocked downstream step;
  it does not cover independent continuation, multiple targets, skipped batches,
  stale continuation context, missing snapshots, or ambiguous write authority.
- The fixture uses declared and observed fixture facts. It does not validate how
  those facts are discovered from notebooks, scripts, existing runners, or
  filesystem artifacts.
- Some missing/stale snapshot or ambiguous-authority cases may assume deeper
  Scopecat adoption than is realistic for an early slice. Treat them as mature
  workflow pressure unless the next validation explicitly targets that stage.
- A user may still need execution help if structured continuation state alone
  does not reduce enough manual queuing and recovery burden.

## Slice Recommendation

Pause before local-executor work.

The assembler reduces the main fixture risk: the summary is no longer only
hand-authored. It does not prove that record-only continuation state is enough
for real use, nor does it earn runner, scheduler, authoring, retry, or
write-back scope.

If the goal is broader product comparison, stop this slice at fixture
validation and compare another validation slice or route before promoting
shared step, review, write, or continuation concepts.

If this slice continues, the next validation should either use an
early-adoption fixture where externally managed snapshot/proposal context is
recorded well enough to resume work, or perform a tightly bounded user/domain
review of whether the assembled summary is enough to resume work. Do not start
local-executor work until that review says the read model is useful but
record-only state is still insufficient.
