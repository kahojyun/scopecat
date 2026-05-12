# Progressive Adoption Progress Tracker

## Purpose

Track durable product and architecture progress for Scopecat without turning
early work into a premature subsystem scaffold.

Current state: `JC-001` has an accepted passive evidence-view decision, a
two-fixture project-owned read-only implementation spike, and a provisional
capability ownership pass for the first wedge. The next step is deciding
whether to seed a small capability map from this provisional ownership pass or
test a second journey before broadening ownership.
This tracker is active, but its W3+ adoption ladders, migration wedges,
capability names, and contract ideas remain hypotheses until the selected W2
journey promotes them.

This tracker is organized around progressive platform adoption:

```text
Journey-first discovery
  -> capability-first adoption ladders
  -> thin vertical migration wedges
  -> contract-first architecture
  -> subsystem specs only when needed
```

## Status Legend

| Status | Meaning |
| --- | --- |
| Not Started | No durable artifact exists yet. |
| Drafting | Early durable artifact exists, but confidence is low. |
| Validating | Being checked against evidence, interviews, or spikes. |
| Ready | Good enough to guide near-term implementation or downstream docs. |
| Promoted | Moved from a narrower working note into the durable product/architecture record. |
| Accepted | Decision-grade; downstream work may depend on it until a reopening trigger fires. |
| Transitional | Extracted research kept temporarily until useful claims move into narrower owner docs. |
| Quarantined | Research input preserved for evidence, pressure, or vocabulary, not accepted as product plan or scope. |
| Deferred | Intentionally postponed. |

## Phase Acceptance Standards

Use decision quality as the acceptance bar. A phase is complete when it creates
the smallest durable artifact that can support the next product or architecture
decision, with evidence, scope limits, non-goals, unresolved risks, and
reopening triggers. It is not complete because every adjacent platform question
has been answered.

General gate for every phase:

- states the decision it supports;
- names the evidence basis and separates direct evidence, inference, baseline
  comparison, latent pressure, and future pressure;
- identifies the next consumer document or implementation decision;
- records explicit non-goals and deferred scope;
- keeps public docs redacted and role-based;
- defines what would reopen or invalidate the conclusion;
- avoids promoting subsystem ownership, storage, UI, execution, or deployment
  scope before a journey, wedge, contract, or spike requires it.

| Phase | Acceptance Check |
| --- | --- |
| W1 Evidence and pain points | Claims are classified by evidence kind, source coverage, visibility, validation route, and redaction boundary. Pains, JTBDs, capability gaps, guardrails, baseline comparisons, and future pressure are not collapsed into one backlog. |
| W2 End-to-end journeys | A concrete current-state and future-state journey crosses capability boundaries, is grounded in a fixture, source map, interview path, or explicit baseline gap, and says which neighboring journeys it excludes. |
| W3 Adoption ladders | Each touched capability has a smallest useful standalone step, a later composition path, a no-adoption-yet boundary, and a reason it is not merely preserving a legacy subsystem shape. |
| W4 Migration wedges | Each wedge has a user-visible outcome, involved capabilities, primary learning goal, migration cost/risk, and reason it is thinner than adjacent wedges. |
| W5 Capability map | Capability names, owners, inputs, outputs, maturity targets, non-goals, and dependency directions are explicit; shared ownership is provisional or intentionally justified. |
| W6 Cross-capability contracts | Concepts have a source of truth, required and optional facts are separated, ambiguity and missing facts are representable, and at least one journey or wedge validates the contract pressure. |
| W7 Technical spikes and prototypes | Each spike has a falsifiable question, fixture/input boundary, pass/fail checks, stop rule, and decision impact. A prototype answers a decision; it does not become a growing product surface by default. |
| W8 Decision promotion | Accepted scope, rejected alternatives, evidence basis, deferred scope, authoritative downstream docs, and reopening triggers are recorded. |
| Implementation readiness | User-facing command/API shape, durability needs, test strategy, package/layout choice, ownership, and migration path are clear enough to avoid accidental architecture. |
| Baseline capability notes | Existing framework or measurement-system comparisons identify what is already solved, what Scopecat should not duplicate, what visible gap remains, and which journey, wedge, or spike will validate that gap. |

Promotion rule: do not expand an earlier-phase artifact just because later-phase
pressure exists. Convert that pressure into a new validation route unless it
directly falsifies the accepted artifact.

## Current Durable Inputs

| Input | Status | Notes |
| --- | --- | --- |
| Documentation policy | Ready | Captured in `README.md` and `AGENTS.md`. |
| Automation architecture notes | Quarantined | Stored as research input; contains broad capability-pressure hypotheses that must be revalidated without accepting subsystem order or scaffolding. |
| Research acceptance-readiness triage | Transitional | `research/extracted/research-acceptance-readiness-triage.md` separates accepted guardrails, evidence, inferences, adoption hypotheses, future pressure, ADR-gated items, and directions not to accept upfront. |
| Legacy experiment code sample validation | Transitional | `research/extracted/legacy-experiment-code-sample-validation.md` validates the research triage and raises companion artifacts, analysis handoff, hardware bring-up, dependency/environment, notebook hygiene, and portability evidence. |
| Evidence and pain-point inventory | Ready | `evidence-and-pain-point-inventory.md` is the W1 owner. `JC-001` has been promoted into the first-wedge document set under `jc-001/`. |
| JC-001 document set | Ready | `jc-001/README.md` is the entry point for the selected journey, wedge, accepted passive evidence-view decision, prototype, and ownership pass. |
| JC-001 journey selection note | Promoted | `jc-001/jc-001-journey-selection-note.md` selected the first W2 candidate and public-safe synthetic fixture boundary. |
| JC-001 work bundle explanation journey | Promoted | `jc-001/jc-001-work-bundle-explanation-journey.md` is the first W2 journey and source for downstream extraction. |
| JC-001 capability adoption extraction | Promoted | `jc-001/jc-001-capability-adoption-extraction.md` extracted touched capabilities, first standalone adoption steps, producer-side minimum facts, and the first W4 wedge candidate. |
| JC-001 migration wedge | Promoted | `jc-001/jc-001-existing-bundle-to-explainable-context-wedge.md` shaped the first thin vertical slice. |
| JC-001 concepts and contracts | Ready | `jc-001/jc-001-concepts-and-contracts.md` defines minimum domain concepts, cross-capability contracts, evidence-view contract, and spike boundary. |
| JC-001 static-analysis spike | Ready | `jc-001/jc-001-static-analysis-spike.md` records the spike question, method, result, decision impact, limits, and follow-up. |
| JC-001 passive evidence-view decision | Accepted | `jc-001/jc-001-passive-evidence-view-decision.md` promotes the validated passive explanation boundary and defers write, execution, hardware, parser, storage, UI, and export-policy scope. |
| JC-001 passive evidence-view prototype scope | Ready | `jc-001/jc-001-passive-evidence-view-prototype-scope.md` defines the implementation-facing prototype target, two-fixture validation, phase-completion standard, and keep-as-prototype decision. |
| JC-001 passive evidence-view capability ownership | Drafting | `jc-001/jc-001-passive-evidence-view-capability-ownership.md` assigns provisional fact/contract ownership for the accepted passive evidence-view wedge without promoting subsystem specs or a full capability map. |

## Workstreams

| ID | Workstream | Status | Durable Output | Exit Criteria |
| --- | --- | --- | --- | --- |
| W1 | Evidence and pain points | Ready | `evidence-and-pain-point-inventory.md` | Major claims link back to interview notes, codebase observations, source coverage, explicit assumptions, or clearly labeled blind-persona adoption pressure; behavioral/scaling priors are separated from evidence; pain, JTBD, capability-gap, guardrail, and baseline statements are distinguished; top-level pain narratives decompose into foundational pain points with visibility and validation route. |
| W2 | End-to-end journeys | Ready | `jc-001/jc-001-work-bundle-explanation-journey.md` | At least one current-state and future-state journey is written across capability boundaries. |
| W3 | Adoption ladders | Drafting | `jc-001/jc-001-capability-adoption-extraction.md` | Each major capability has a smallest useful standalone adoption step and upgrade path. |
| W4 | Migration wedges | Ready | `jc-001/jc-001-existing-bundle-to-explainable-context-wedge.md` | Candidate vertical slices are ranked by user value, migration cost, and architectural learning. |
| W5 | Capability map | Drafting | `jc-001/jc-001-passive-evidence-view-capability-ownership.md` | Capabilities, ownership, non-goals, and maturity targets are explicit. |
| W6 | Cross-capability contracts | Ready | `jc-001/jc-001-concepts-and-contracts.md` | Shared concepts and references have one owner and clear dependency direction. |
| W7 | Technical spikes | Ready | `jc-001/jc-001-static-analysis-spike.md` | Each spike has a question, result, decision impact, and follow-up. |
| W8 | Decision promotion | Ready | `jc-001/jc-001-passive-evidence-view-decision.md` | Validated conclusions are promoted out of research notes. |

## Adoption Ladders To Define

The `JC-001`-touched rows now include promoted first-wedge learning. Rows still
marked `Not Started` remain W1 hypotheses for later W3 work; they do not define
a capability map or promote implementation scope before a W2 journey validates
the need.

| Capability | Starting User Pain | First Standalone Adoption Step | Later Composition Path | Status |
| --- | --- | --- | --- | --- |
| Measurement History | Data and run records are scattered or fragile. | Open an existing work bundle and produce an artifact-role inventory anchored by a run-like or bundle identity. | Later run records can link scan points, parameter snapshots, code versions, execution records, and remote runs into history. | Drafting |
| Scan Framework | Scan loops are ad hoc and hard to preview. | A standalone scan plan expands points and previews desired state without hardware. | Plans write scan-point records, bind parameter snapshots, and become frozen remote execution packages. | Not Started |
| Parameter Memory | Configs, calibrations, and notes drift across files. | Show selected settings, copied snapshots, generated context, variants, conflicts, freshness, and unknown active state as evidence. | Calibration workflows propose updates, review diffs, and link accepted snapshots to runs. | Drafting |
| Code Asset Registry | Scripts and drivers are copied across experiments and machines. | Register or infer code references that explain settings path selection and derivation flow without executing them. | Managed execution and instrument runtime resolve exact code versions after safety boundaries exist. | Drafting |
| Instrument Runtime | Setup and shared-resource context is easy to lose or misuse. | Record setup or registry-like context as declared or observed evidence before device control. | Leases and apply semantics require explicit safety ADRs before becoming adoption steps. | Drafting |
| Managed Code Runner | Script execution is hard to trust across local control computers, but control PCs must not become more fragile. | Show readiness gaps and dependency-shaped clues as static evidence. | Workflow and remote execution use runner records as provenance after control-PC service, rollback, and mutation boundaries are decided. | Drafting |
| Comparability and known-good diff | Valid-looking runs and setup states are hard to compare across non-identical systems, method variants, calibration state, and analysis choices. | Explain conflicts between artifacts inside one bundle with layer-by-layer evidence. | Plan preview, calibration review, setup manifests, campaign navigation, and handoff records use the same comparison evidence once their boundaries are validated. | Drafting |
| Declared physical context and local schemas | Physical wiring, chip topology, aliases, attenuation, and experiment parameters are hard to verify from software and hard to fit into one universal schema. | One bounded setup, sample, or campaign records a small declared schema with source, freshness, validity, and verification status, then uses it for lookup, calculation, visualization, comparison, or handoff. | Setup maps, comparability review, calibration impact, layout views, and diagnostics build on versioned local schemas once useful fields are proven. | Not Started |
| Analysis and claim lineage | Figures, fits, reports, and conclusions lose links back to raw data, processing choices, calibration context, and rerun history. | A report, figure, or derived artifact links back to source runs, code, context, corrections, fits, exclusions, and unresolved ambiguity. | Publication review, calibration-impact checks, campaign summaries, and handoff packages build on the same lineage model after W2 validates the first fixture. | Not Started |

## Candidate Migration Wedges

The `JC-001` wedge row is promoted as the accepted first passive evidence-view
slice. The remaining rows are W1 hypotheses for later W4 work; future wedge
priority should be decided from evidence, user value, migration cost,
architectural learning, and whether a pain is directly visible or latent behind
constrained legacy workflows.
Experiment real-time visualization, durable measurement records, and existing
measurement-framework baselines should be handled as later baseline-capability
or journey pressure unless they directly falsify the passive evidence-view
boundary above.

| Wedge | User-Visible Outcome | Capabilities Involved | Main Learning Goal | Status |
| --- | --- | --- | --- | --- |
| Existing run/work bundle to explainable context bundle | A user opens an existing work bundle and sees anchor artifacts, selected context candidates, code-shaped provenance, generated sidecars, copied snapshots, variants, ambiguity, producer-fact gaps, and sharing boundaries without mutation. | Measurement History, Parameter Memory, Code Asset Registry, Instrument Runtime, Managed Code Runner, Comparability and known-good diff | Test whether passive explanation across context, code, generated/copied artifacts, variants, and producer gaps is the strongest first wedge before new writes, managed execution, known-good comparison, or a Measurement History-only first goal. | Ready |
| Known-good reference to readiness and diagnostic comparison | A user compares a current bundle or machine against a selected known-good reference, sees confidence gaps, and can share a full-fidelity internal diagnostic package or a sanitized package when crossing public, external, or restricted support boundaries. | Measurement History, Parameter Memory, Code Asset Registry, Managed Code Runner, Instrument Runtime | Test blind-persona adoption blockers around truth drift, false confidence, control-PC fragility, rollback pressure, and support diagnostics without accepting config authority, environment management, or device control. | Not Started |
| Two valid runs to scientific comparability review | A user compares two valid-looking runs, setup states, or method variants and sees which context, calibration, setup, generated-protocol, correction, and analysis differences matter for comparison. | Measurement History, Parameter Memory, Code Asset Registry, Scan Framework, Instrument Runtime, Comparability and known-good diff, Analysis and claim lineage | Test the external-framework capability gap: Scopecat should complement existing measurement systems by explaining whether results can be compared, migrated, or handed off, not by replacing acquisition/control/calibration frameworks. | Not Started |
| Small declared setup schema to useful context output | A user maintains a minimal local schema for one setup, sample, or campaign because it immediately enables a qubit-to-instrument lookup, attenuation calculation, chip-layout parameter view, comparability check, or handoff. | Parameter Memory, Instrument Runtime, Declared physical context and local schemas, Comparability and known-good diff | Test whether manually maintained physical and schema context earns its cost before adding broad setup inventory, topology databases, or universal parameter models. | Not Started |
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

## Near-Term Execution Plan

| Step | Action | Expected Durable Output | Depends On |
| --- | --- | --- | --- |
| 1 | Use the W1 evidence inventory as the distilled research input. | No new document; `evidence-and-pain-point-inventory.md` is the current W1 owner. | W1 ready state. |
| 2 | Create a fixture source map and journey-selection note. Default to `JC-001` unless the selected fixture rejects it; first map anchor objects, artifact roles, active/obsolete/cache status, notebook source-cell extraction, opaque binary handling, provenance relations, and sharing boundaries. Keep any full-fidelity map with exact local paths, tree names, system labels, sample labels, usernames, or instrument identifiers in a non-public W2 working artifact; public docs should use redacted or role-based labels. Then use top-level pain narratives as journey seeds and foundational pains as acceptance pressure, based on direction-bias corrected evidence, pain visibility, validation route, and statement kind rather than subsystem preference. Behavioral/scaling priors may generate prompts, but should not rank the journey without validation. | Completed by non-public fixture source map work plus `jc-001/jc-001-journey-selection-note.md`. | `evidence-and-pain-point-inventory.md`. |
| 3 | Write the selected journey in current-state and future-state form. | Completed by `jc-001/jc-001-work-bundle-explanation-journey.md`. | `jc-001/jc-001-journey-selection-note.md`. |
| 4 | Identify the capabilities touched by that journey and their standalone adoption steps. | Completed by `jc-001/jc-001-capability-adoption-extraction.md`. | `jc-001/jc-001-work-bundle-explanation-journey.md`. |
| 5 | Shape one candidate migration wedge from the selected journey. | Completed by `jc-001/jc-001-existing-bundle-to-explainable-context-wedge.md`. | `jc-001/jc-001-capability-adoption-extraction.md`. |
| 6 | Identify the minimum domain concepts and contracts needed for that wedge. | Completed by `jc-001/jc-001-concepts-and-contracts.md`. | `jc-001/jc-001-existing-bundle-to-explainable-context-wedge.md`. |
| 7 | Run a technical spike only after the wedge scope is explicit. | Completed by `jc-001/jc-001-static-analysis-spike.md`. | `jc-001/jc-001-concepts-and-contracts.md`. |
| 8 | Promote validated decisions into ADRs or architecture docs. | Completed by `jc-001/jc-001-passive-evidence-view-decision.md`. | Step 7. |
| 9 | Shape the first implementation-facing prototype scope for the accepted passive evidence-view boundary. | Completed by `jc-001/jc-001-passive-evidence-view-prototype-scope.md`. | Step 8. |
| 10 | Choose the prototype fixture strategy. | Completed by the selected committed public-safe test-fixture strategy in `jc-001/jc-001-passive-evidence-view-prototype-scope.md`. | Step 9. |
| 11 | Start the implementation spike. | Completed by `prototypes/jc001_passive_evidence_view.py`, `tests/fixtures/jc001-layered-config-bundle/`, and `tests/test_jc001_passive_evidence_view.py`. | Step 10. |
| 12 | Review the implementation spike output. | Completed by `jc-001/jc-001-passive-evidence-view-prototype-scope.md`; keep iterating as a prototype script and do not promote package layout or tooling yet. | Step 11. |
| 13 | Harden the prototype within fixture-sized boundaries. | Completed with manifest validation, clearer error messages, and compact expected-shape snapshot without broad parser, package, storage, or UI promotion. | Step 12. |
| 14 | Decide whether a second public-safe fixture shape is needed. | Completed by `tests/fixtures/jc001-minimal-unknown/`; the second fixture validates absence handling, unknown artifacts, readiness hints, single-anchor behavior, and zero-conflict output. | Step 13. |
| 15 | Return to product/architecture work before further implementation. | Completed by `jc-001/jc-001-passive-evidence-view-capability-ownership.md`, a narrow ownership pass that does not promote package layout, parser architecture, or subsystem specs. | Step 14. |
| 16 | Decide whether to seed a small capability map or test a second journey first. | Either a small provisional-owner capability map or a second journey-selection note that tests ownership pressure before broader capability mapping. | Step 15. |

## Review Cadence

Review this tracker whenever a durable product or architecture document is
created, removed, or promoted out of research.

During review:

- update statuses;
- add links to durable outputs;
- retire wedges that no longer match the product direction;
- avoid adding new workstreams unless they change how the project is managed.

## Guardrails

- Do not split product discovery by subsystem.
- Do not create subsystem specs before journeys, adoption ladders, and
  contracts justify them.
- Do not require full-platform adoption for the first useful slice.
- Do not let standalone adoption stories become incompatible mini-products.
- Keep each wedge narrow enough to validate with one concrete workflow.
