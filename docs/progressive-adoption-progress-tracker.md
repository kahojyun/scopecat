# Progressive Adoption Progress Tracker

## Purpose

Track durable product and architecture progress for Scopecat without turning
early work into a premature subsystem scaffold.

Current state: `JC-001` has an accepted passive evidence-view decision, a
static-analysis spike, a two-fixture read-only prototype scope, a
fixture-validated manifest/public-output contract, and a provisional capability
ownership pass for the first wedge. `JC-002` now has a drafting document set
and a fixture-backed read-only handoff snapshot prototype. The current decision
point is whether the `JC-002` fixture is strong enough to promote an accepted
prototype boundary or whether another lab scenario should challenge it first.
This tracker is active. Unpromoted W3+ adoption ladders, migration wedges,
capability names, and contract ideas remain hypotheses until a selected W2
journey promotes them.

Keep this tracker compact. It may hold the current phase table, the current
decision point, and small hypothesis inventories while there is only one active
accepted wedge. When multiple journeys, adoption ladders, migration wedges,
baseline-capability analyses, or shared contracts become active, move the
durable detail into a narrower owner document and leave only phase and links
here.

This tracker is organized around progressive platform adoption:

```text
Journey-first discovery
  -> capability-first adoption ladders
  -> thin vertical migration wedges
  -> contract-first architecture
  -> subsystem specs only when needed
```

## Phase Legend

The tracker uses phase labels for workstreams and inventories.

| Phase | Meaning |
| --- | --- |
| Not Started | No durable artifact exists yet. |
| Drafting | Early durable artifact exists, but confidence is low. |
| Provisional | Evidence pressure is explicit, but the project has not promoted it into the next durable map or adoption plan. |
| Validating | Being checked against evidence, interviews, or spikes. |
| Ready | Good enough to guide near-term implementation or downstream docs. |
| Promoted | Moved from a narrower working note into the durable product/architecture record. |
| Accepted | Decision-grade; downstream work may depend on it until a reopening trigger fires. |
| Transitional | Extracted research kept temporarily until useful claims move into narrower owner docs. |
| Quarantined | Research input preserved for evidence, pressure, or vocabulary, not accepted as product plan or scope. |
| Deferred | Intentionally postponed. |

## Decision Quality Bar

A phase is complete when it creates the smallest durable artifact that can
support the next product or architecture decision. Each promoted artifact should
state:

- the decision it supports;
- the evidence basis, with direct evidence, inference, baseline comparison, and
  future pressure kept separate;
- the next consumer document or implementation decision;
- the explicit non-goals or deferred scope;
- the reopening trigger.

Do not expand an earlier-phase artifact just because later-phase pressure
exists. Convert that pressure into a new validation route unless it directly
falsifies the accepted artifact.

## Current Durable Inputs

| Input | Phase | Notes |
| --- | --- | --- |
| Documentation policy | Ready | Captured in `README.md` and `AGENTS.md`. |
| Automation architecture notes | Quarantined | Stored as research input; contains broad capability-pressure hypotheses that must be revalidated without accepting subsystem order or scaffolding. |
| Research acceptance-readiness triage | Transitional | `research/extracted/research-acceptance-readiness-triage.md` separates accepted guardrails, evidence, inferences, adoption hypotheses, future pressure, ADR-gated items, and directions not to accept upfront. |
| Legacy experiment code sample validation | Transitional | `research/extracted/legacy-experiment-code-sample-validation.md` validates the research triage and raises companion artifacts, analysis handoff, hardware bring-up, dependency/environment, notebook hygiene, and portability evidence. |
| Evidence and pain-point inventory | Ready | `evidence-and-pain-point-inventory.md` is the W1 owner. `JC-001` has been promoted into the first-wedge document set. |
| JC-001 first-wedge document set | Ready | `jc-001/README.md` owns the detailed reading order for the first accepted wedge. |
| JC-002 analysis handoff document set | Validating | `jc-002/README.md` owns the selected-run handoff journey and links to the first fixture-backed prototype. |

## Workstreams

| ID | Workstream | Phase | Durable Output | Exit Criteria |
| --- | --- | --- | --- | --- |
| W1 | Evidence and pain points | Ready | `evidence-and-pain-point-inventory.md` | Major claims link back to interview notes, codebase observations, source coverage, explicit assumptions, or clearly labeled blind-persona adoption pressure; behavioral/scaling priors are separated from evidence; pain, JTBD, capability-gap, guardrail, and baseline statements are distinguished; top-level pain narratives decompose into foundational pain points with visibility and validation route. |
| W2 | End-to-end journeys | Ready | `jc-001/jc-001-work-bundle-explanation-journey.md` | At least one current-state and future-state journey is written across capability boundaries. |
| W3 | Adoption ladders | Provisional | `jc-001/jc-001-capability-adoption-extraction.md` | JC-001 adoption pressure is explicit without promoting a broader adoption plan; promote to drafting after the next product/architecture choice. |
| W4 | Migration wedges | Ready | `jc-001/jc-001-existing-bundle-to-explainable-context-wedge.md` | The accepted `JC-001` passive evidence-view wedge is ready; broader wedge ranking remains future W4 work. |
| W5 | Capability map | Provisional | `jc-001/jc-001-passive-evidence-view-capability-ownership.md` | JC-001 ownership pressure is explicit without promoting a broader capability map; promote to drafting after either a small map is selected or a second journey tests the owners. |
| W6 | Cross-capability contracts | Ready | `jc-001/jc-001-concepts-and-contracts.md` | Shared concepts, provisional owner pressure, and dependency direction are explicit for the accepted wedge. |
| W7 | Technical spikes and prototypes | Ready | `jc-001/jc-001-static-analysis-spike.md`; `jc-001/jc-001-passive-evidence-view-prototype-scope.md` | The static-analysis spike has a question, result, decision impact, and follow-up; the read-only prototype scope records two-fixture validation. |
| W8 | Decision promotion | Accepted | `jc-001/jc-001-passive-evidence-view-decision.md` | The passive evidence-view boundary is accepted at fixture scale. |

## Adoption Ladders To Define

The `JC-001`-touched rows now include provisional first-wedge pressure only.
Rows marked `Provisional` are not seeded capability-map work yet. Rows marked
`Not Started` remain W1 hypotheses for later W3 work; they do not define a
capability map or promote implementation scope before a W2 journey validates
the need.

This table is a staging inventory, not the durable capability map. Promote a
capability row into a dedicated owner document only after a second journey or an
implementation decision shows that the same fact family needs durable ownership.

| Capability | Starting User Pain | Provisional First-Step Pressure | Possible Later Composition | Phase |
| --- | --- | --- | --- | --- |
| Measurement History | Data and run records are scattered or fragile. | Open an existing work bundle and produce an artifact-role inventory anchored by a run-like or bundle identity. | Later run records can link scan points, parameter snapshots, code versions, execution records, and remote runs into history. | Provisional |
| Scan Framework | Scan loops are ad hoc and hard to preview. | A standalone scan plan expands points and previews desired state without hardware. | Plans write scan-point records, bind parameter snapshots, and become frozen remote execution packages. | Not Started |
| Parameter Memory | Configs, calibrations, and notes drift across files. | Show selected settings, copied snapshots, generated context, variants, conflicts, freshness, and unknown active state as evidence. | Calibration workflows propose updates, review diffs, and link accepted snapshots to runs. | Provisional |
| Code Asset Registry | Scripts and drivers are copied across experiments and machines. | Surface code-shaped evidence that explains settings path selection and derivation flow without executing it. | Managed execution and instrument runtime resolve exact code versions after safety boundaries exist. | Provisional |
| Instrument Runtime | Setup and shared-resource context is easy to lose or misuse. | Represent setup or registry-like context as declared or observed evidence before device control. | Leases and apply semantics require explicit safety ADRs before becoming adoption steps. | Provisional |
| Managed Code Runner | Script execution is hard to trust across local control computers, but control PCs must not become more fragile. | Show readiness gaps and dependency-shaped clues as static evidence. | Workflow and remote execution use runner records as provenance after control-PC service, rollback, and mutation boundaries are decided. | Provisional |
| Comparability and conflict review | Valid-looking runs and setup states are hard to compare across non-identical systems, method variants, calibration state, and analysis choices. | Explain conflicts between artifacts inside one bundle with layer-by-layer evidence. | Plan preview, calibration review, setup manifests, campaign navigation, and handoff records use the same comparison evidence once their boundaries are validated. | Provisional |
| Declared physical context and local schemas | Physical wiring, chip topology, aliases, attenuation, and experiment parameters are hard to verify from software and hard to fit into one universal schema. | One bounded setup, sample, or campaign records a small declared schema with source, freshness, validity, and verification status, then uses it for lookup, calculation, visualization, comparison, or handoff. | Setup maps, comparability review, calibration impact, layout views, and diagnostics build on versioned local schemas once useful fields are proven. | Not Started |
| Analysis and claim lineage | Figures, fits, reports, and conclusions lose links back to raw data, processing choices, calibration context, and rerun history. | A report, figure, or derived artifact links back to source runs, code, context, corrections, fits, exclusions, and unresolved ambiguity. | Publication review, calibration-impact checks, campaign summaries, and handoff packages build on the same lineage model after W2 validates the first fixture. | Not Started |

## Candidate Migration Wedges

The `JC-001` wedge row is ready because it is backed by the accepted passive
evidence-view decision. The `Starred runs to analysis handoff package` row is
validating because a lightweight `JC-002` document set, synthetic fixture,
and read-only prototype now exist, but it is not an accepted journey,
manifest/API/storage/UI contract, or implementation scope. The remaining rows
are W1 hypotheses for later
W4 work; future wedge priority should be decided from evidence, user value,
migration cost, architectural learning, and whether a pain is directly visible
or latent behind constrained legacy workflows.
Recent user-context refinement raises internal analysis handoff above
cross-machine scientific comparison as a nearer adoption pressure: users need
to find high-value runs on an experiment-control computer and move selected
data plus context to an analysis computer without losing source identity. The
current candidate detail, validation coverage, and live-preview boundary are
owned by
[`jc-002/README.md`](jc-002/README.md).

This table should stay short. If multiple wedges need active coordination at
the same time, create a narrower migration-wedge owner note and keep only links
and statuses in this tracker.

| Wedge | User-Visible Outcome | Capabilities Involved | Main Learning Goal | Phase |
| --- | --- | --- | --- | --- |
| Existing run/work bundle to explainable context bundle | A user opens an existing work bundle and sees anchor artifacts, selected context candidates, code-shaped provenance, generated sidecars, copied snapshots, variants, ambiguity, producer-fact gaps, and sharing boundaries without mutation. | Measurement History, Parameter Memory, Code Asset Registry, Instrument Runtime, Managed Code Runner, Comparability and conflict review | Test whether passive explanation across context, code, generated/copied artifacts, variants, and producer gaps is the strongest first wedge before new writes, managed execution, known-good comparison, or a Measurement History-only first goal. | Ready |
| [Starred runs to analysis handoff package](jc-002/README.md) | A user finds high-value runs, multi-selects them like files, and creates an immutable pre-analysis data-plus-context handoff snapshot for personal analysis work. | Measurement History, Analysis and claim lineage, Parameter Memory, Code Asset Registry | Test the adoption-critical path from experiment-control computer to personal analysis computer with local offline GUI/Python-reader consumption, without requiring generic export formats first, full work-bundle export/import, managed script execution, a permission system, publication workflow scope, generated-report scope, live-monitor semantics, or premature reader/API/storage/UI contracts. | Validating |
| Known-good reference to readiness and diagnostic comparison | A user compares a current bundle or machine against a selected known-good reference, sees confidence gaps, and can share a full-fidelity internal diagnostic package or a sanitized package when crossing public, external, or restricted support boundaries. | Measurement History, Parameter Memory, Code Asset Registry, Managed Code Runner, Instrument Runtime | Test blind-persona adoption blockers around truth drift, false confidence, control-PC fragility, rollback pressure, and support diagnostics without accepting config authority, environment management, or device control. | Not Started |
| Two valid runs to scientific comparability review | A user compares two valid-looking runs, setup states, or method variants and sees which context, calibration, setup, generated-protocol, correction, and analysis differences matter for comparison. | Measurement History, Parameter Memory, Code Asset Registry, Scan Framework, Instrument Runtime, Comparability and conflict review, Analysis and claim lineage | Test the external-framework capability gap: Scopecat should complement existing measurement systems by explaining whether results can be compared, migrated, or handed off, not by replacing acquisition/control/calibration frameworks. | Not Started |
| Small declared setup schema to useful context output | A user maintains a minimal local schema for one setup, sample, or campaign because it immediately enables a qubit-to-instrument lookup, attenuation calculation, chip-layout parameter view, comparability check, or handoff. | Parameter Memory, Instrument Runtime, Declared physical context and local schemas, Comparability and conflict review | Test whether manually maintained physical and schema context earns its cost before adding broad setup inventory, topology databases, or universal parameter models. | Not Started |
| Figure or report to analysis-impact lineage | A user starts from a figure, fit, report, or derived artifact and sees the source runs, processing code, correction choices, calibration context, setup assumptions, and unresolved ambiguity that affect the claim. | Measurement History, Code Asset Registry, Parameter Memory, Analysis and claim lineage | Test whether acquisition provenance plus analysis lineage can answer downstream trust and impact questions without becoming a full ELN or report generator. | Not Started |
| Ordinary Python script to durable measurement record | A simple script writes data, supports live inspection, survives interruption, and reopens by stable ID. | Measurement History | Validate durable-record substrate without displacing the workflow-bundle first goal. | Not Started |
| Legacy scan loop to previewable scan plan | A user replaces nested loops with a plan that can preview scan points before execution. | Scan Framework, Measurement History | Test scan semantics without requiring hardware control. | Not Started |
| Scattered config files to parameter snapshot | A script uses a frozen parameter snapshot instead of local config drift. | Parameter Memory, Measurement History | Separate durable parameters from scan-local variables. | Not Started |
| Copied scripts to code asset reference | A run records which external script, commit, and entrypoint were used. | Code Asset Registry, Measurement History | Separate code identity from execution identity. | Not Started |
| Manual instrument coordination to resource lease | Legacy code obtains an exclusive lease before controlling shared hardware. | Instrument Runtime | Validate the minimal live-resource model. | Deferred |
| Local script to managed execution record | A script runs under supervision with logs, artifacts, status, and environment capture. | Managed Code Runner, Code Asset Registry | Separate execution records from code identity. | Deferred |
| Local preview to remote dry run | A locally authored package validates remotely without touching hardware. | Scan Framework, Remote Execution, Code Asset Registry, Parameter Memory | Test immutable plan and validation contracts. | Deferred |

For W2 validation, use the current generic lab context: Windows-heavy
instrument-control machines, multiple non-identical systems, personnel
turnover, and uneven technical ownership. Ordinary experiment users should not
need to become driver, deployment, machine maintenance, or
lab-knowledge-management owners to get value from the first slices. External
framework baselines also mean early wedges should complement existing
acquisition, control, data, and calibration systems rather than replace them.
Manual physical-context and schema maintenance should start only where it
produces immediate lookup, calculation, visualization, comparison, handoff, or
diagnostic value. Early wedges should avoid adding mandatory network services,
cloud login, heavy background agents, or automatic driver/environment mutation
to working control computers.

## Near-Term Coordination

Completed path:

```text
W1 evidence inventory
  -> JC-001 journey and wedge
  -> accepted passive evidence-view decision
  -> two-fixture prototype
  -> provisional ownership pass
```

This section is a coordination surface, not the owner of every active journey's
next step. Keep per-`JC` next decisions in that `JC`'s README, scope document,
or decision record, then link from the tracker only when a status, phase, or
cross-journey dependency changes.

Active coordination points:

- `JC-002`: decide whether the handoff snapshot prototype earns an accepted
  fixture-scale boundary, needs another scenario, or should feed back into a
  small capability map with the `JC-001` ownership pass.

Parallel-work rule:

- A journey-local PR may update this tracker only to add or revise a link,
  phase, or short coordination point required by the changed journey.
- A journey-local PR should not reorder global priorities, replace another
  journey's active decision, or turn this section into a queue of next tasks.
- If two or more active `JC` PRs need to change priority, shared contract
  ownership, migration-wedge ranking, or accepted sequence, use a small
  coordination PR that updates this tracker after the affected journey owner
  docs are clear.
- If this section starts carrying detailed coordination for multiple wedges,
  create a narrower owner note for that shared coordination and keep only links
  and statuses here.

## Review Cadence

Review this tracker whenever a durable product or architecture document is
created, removed, or promoted out of research.

During review:

- update phases;
- add links to durable outputs;
- retire wedges that no longer match the product direction;
- move growing ladder, wedge, baseline, or contract detail into narrower owner
  docs once it has more than one active consumer;
- avoid adding new workstreams unless they change how the project is managed.

## Guardrails

- Do not split product discovery by subsystem.
- Do not create subsystem specs before journeys, adoption ladders, and
  contracts justify them.
- Do not require full-platform adoption for the first useful slice.
- Do not let standalone adoption stories become incompatible mini-products.
- Keep each wedge narrow enough to validate with one concrete workflow.
