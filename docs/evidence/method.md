# Evidence Method

## Status

Ready evidence-method owner.

This document owns interpretation rules for evidence and problem-framing
hygiene. It is not the evidence register, product vision, research index,
validation owner, or architecture decision.

## Purpose

Keep [`inventory.md`](inventory.md) focused on stable `EV-*` evidence claims.
Use this document to interpret source confidence, bias correction, source
handling, problem-framing promotion, and option hygiene.

## Analysis Layer Boundaries

Treat neighboring analysis steps as work that may happen in one pass, not as
permission to merge their durable artifacts.

| Work layer | Usually belongs together | Durable owner |
| --- | --- | --- |
| Source intake and evidence hygiene | Source material, extraction, claim classification, source posture, and bias triage. | Research notes, extracted research files, `inventory.md`, and this method document. |
| Problem framing | Problem or pressure clustering, workflow/domain analysis, assumptions, and risks. | `../discovery/problem-briefs/`, extracted research notes, or discovery docs when framing changes hypotheses. |
| Option exploration | Adoption hypotheses, scenario candidates, validation questions, and charter drafting. | Discovery docs or a narrow validation owner; do not treat options as accepted scope. |
| Validation and disposition | User validation, reference-case validation, prototype validation, acceptance, deletion, or deferral. | The owning validation, decision, tracker, or reference-case document. |
| Contracts and architecture | Stable vocabulary, API/schema/storage contracts, ownership boundaries, and ADRs. | Future `architecture/` content only when blocked or accepted scope needs it. |

The critical separations are:

```text
evidence hygiene != problem framing
problem framing != option exploration
option exploration != validation result
validation result != product contract
```

## Bias Correction

Treat source families separately:

- Fricon predecessor lessons are useful evidence, but over-emphasize
  measurement history and stable reopen.
- The workflow improvement case adds current friction around notebooks, copied
  code, parameter and registry files, wiring sheets, generated artifacts,
  derived arrays, environment coupling, and report handoff.
- Current-owner clarification is useful for narrowing intended pains and
  workarounds, but it is not independent user research. Mark it clearly and
  require later validation before using it as accepted demand.
- Historical automation discussion is low-confidence design pressure, not
  source evidence or accepted subsystem order.
- Blind persona and capability-gap role-play are prompt-method checks, not
  user research.
- Behavioral and scaling priors help generate hypotheses, but can narrow
  thinking toward messy exploratory labs, rescue workflows, superconducting
  wiring concerns, anti-schema bias, and passive capture.

Separate three judgments that were previously easy to collapse:

- whether a claim is well supported by evidence;
- which source families support it;
- whether it is a high-leverage Scopecat improvement target.

## Evidence Classes

| Class | Meaning | Handling |
| --- | --- | --- |
| Observation | Directly observed in extracted notes or code-sample review. | Safe to cite as evidence with portability caveats; redact for public use. |
| Evidence-backed inference | Reasoned conclusion supported by multiple observations. | Candidate for problem framing or narrow promotion. |
| Latent pressure | Plausible pain hidden by the old workflow's limits. | Preserve with source and validation route; do not treat as accepted scope. |
| Hypothesis | Plausible product shape, UX, ordering, or API. | Keep out of accepted scope until validation. |
| Future pressure | Likely later capability pressure. | Preserve room for it; do not implement from evidence alone. |
| ADR-gated | Mutation, compatibility, storage, distributed, remote, safety, or AI-action risk. | Requires explicit decision before acceptance. |

Support strength is claim-level support only. It does not mean a pain is
urgent, ready for implementation, or especially high leverage.

## ID Rules

`EV-*` is the only stable evidence ID family. After an evidence ID is
referenced from another document, do not renumber it. Add a new row instead.

Problem framing now uses named problem-brief documents rather than durable pain
IDs. If a problem brief needs a stable reference, link to the brief filename
and heading.

## Problem-Framing Rubric

Use problem briefs to move from evidence toward user-facing failures. A good
brief separates:

- observed sample evidence;
- project-owner clarification;
- derived hypotheses;
- premature or solution-shaped scope;
- possible validation questions.

Do not promote a brief directly into product scope. A brief becomes useful
when it helps choose a smaller next question, not when it accumulates the most
capabilities.

Prefer problem statements that name the current user failure and workaround:

```text
I cannot tell which code, context, setup facts, and generated artifacts are
safe to reuse, so I copy or preserve a whole working bundle before changing it.
```

A scenario or validation charter may then phrase the situational job:

```text
When I need to reuse a protocol on a screening setup, help me compare the
current bundle against a known-good reference so I can decide what must be
checked before spending experiment time.
```

The pain explains why the scenario matters. The capability describes what the
system might do. The baseline states what a reasonable measurement/data system
is already expected to provide.

## Updating Evidence

When evidence changes, use these prompts:

- If a new row changes a problem brief or adoption hypothesis, update that
  owner.
- If a source is messy, biased, generated, or historical, preserve the useful
  pressure and label its class instead of either deleting it or over-promoting
  it.
- If several steps happen in one work session, still record the durable claim
  in the narrowest owner for its layer.
- If a prompt, role-play, or blind review produces a useful idea, tie it to
  source evidence or mark it as latent pressure before it influences scope.
- If a discussion introduces a solution-shaped concept such as code registry,
  managed runner, automatic version management, proposal workflow, central
  database, shared-storage service, runtime handoff, or universal metadata,
  first recover the user-visible pain that made the concept attractive.
- If pain is caused by code or execution fragmentation, distinguish the
  minimum useful integrated support from a full runtime product.

## Source Handling Guardrails

- Treat LabRAD, Data Vault numeric IDs, `idx` filenames, latest-file lookups,
  local counters, and local folder conventions as source conventions and
  reference cases, not product concepts.
- Use "companion artifact" as the product-neutral term. "Sidecar" is legacy
  evidence vocabulary.
- Treat notebooks as current-state workflow spines and provenance evidence; do
  not infer automatic notebook-state capture.
- Treat parameter files, registry files, wiring sheets, generated summaries,
  and setup files as opaque context candidates unless a later model owns their
  semantics.
- Treat physical wiring, mounted sample state, chip topology, line attenuation,
  and alias maps as declared or externally evidenced state unless a validation
  path exists.
- Prefer local, versioned, evolvable schemas over a universal parameter or
  setup ontology in early validation work.
- Require manual setup or topology maintenance to earn its keep through
  lookup, calculation, visualization, comparison, handoff, or diagnostics.
- Surface source, provenance, freshness, ambiguity, selected/proposed/applied
  status, and missing facts. Do not claim Scopecat can infer authoritative
  truth from arbitrary legacy files.
- Avoid creating a parallel truth store. Early records should label observed,
  declared, selected, proposed, applied, missing, stale, and unchecked state.

## Prompt-Method Guardrails

When using behavioral priors or role-play:

- include at least one no-prior control role for the same question;
- ask prior-informed roles which priors helped and which narrowed thinking;
- rotate role lenses beyond ordinary operator and maintainer when analysis,
  handoff, governance, or scale matters;
- avoid naming the current product, repository documents, local samples, or
  previous problem framing in the prompt;
- do not promote generated pains unless they map to evidence-backed problems
  with visibility, source coverage, and a validation route.

## Decision Source Hygiene

Some constraints come from repository process rather than lab-user pain. Keep
them in their lane.

| Source of pressure | Valid use | Do not convert into |
| --- | --- | --- |
| Public-docs redaction rules | Redact public docs and exports; treat local identifiers as portability and reuse evidence. | A product requirement for internal redaction workflows without user evidence. |
| Research extraction policy | Keep raw input, extracted claims, and promoted decisions separate. | A visible product extraction workflow. |
| Durable-doc ownership policy | Put accepted facts in the smallest owning project doc. | A product information architecture or database model. |
| Scenario discipline | Delay capability/spec promotion until a concrete scenario explains the need. | Proof that the first route must follow tracker order. |
| Legacy workflow conventions | Use as current-state evidence and reference cases. | Features that preserve fragile old workflows as preferred behavior. |
| Engineering safety reasoning | Mark mutation, compatibility, central storage, remote execution, and AI action as ADR-gated. | User pain unless tied back to workflow evidence. |

## Design Pressures

Historical discussions and predecessor work preserve useful pressures that a
run-history-only product would miss. Use these as scenario-selection prompts,
not as accepted subsystem names:

| Design pressure | Evidence support | Why preserve it |
| --- | --- | --- |
| Run and bundle evidence | EV-001, EV-002, EV-003, EV-010, EV-016 | Useful anchor for identity, data, lifecycle, and context, but not enough by itself to differentiate Scopecat. |
| Scan semantics and preview | EV-010, EV-016, EV-019, EV-021, EV-024 | Pre-run plan pressure needs representation before device apply or workflow orchestration. |
| Settings, calibration, and context evidence | EV-004, EV-005, EV-015, EV-043 | Current files create source-of-truth ambiguity; start with candidate states, local schemas, prior-version retry, branch/working-point history, and bad-state exclusion before write-back scope. |
| Code and dependency provenance | EV-006, EV-008, EV-021, EV-025, EV-050 | Code identity and selection are separate from execution ownership. |
| Setup and runtime boundary evidence | EV-011, EV-031, EV-037, EV-041, EV-042 | Setup context is real, but live control and leases require validation and safety decisions. |
| Execution readiness and lifecycle evidence | EV-007, EV-021, EV-023, EV-024, EV-026, EV-027, EV-032 | Readiness, grouped calibration intent, review gates, requested next action, known-good references, failure policy, and outcome records matter before schedulers or managed runners. |
| Handoff and lineage | EV-009, EV-017, EV-018, EV-019, EV-022, EV-025, EV-028, EV-029, EV-030, EV-033, EV-044, EV-045 | Derived results, corrections, run families, reports, handoff, false-confidence risk, and data-shape evidence guide future scenario selection. |
| Running-run readability | EV-046, EV-047 | Measurement-time feedback should start from explicit recorded data and non-intrusive consumers before automated advice is promoted. |
| Cross-machine record movement | EV-048, EV-049 | Portable records, export/import, and optional shared-storage discovery should be tested before remote execution or central services. |

## External Baseline Rule

Use [`external-baseline.md`](external-baseline.md) as a differentiation
baseline, not as competitive claims. Mature systems already cover many
acquisition, metadata, instrument, scheduler, and calibration concerns.
Scopecat's gap should stay focused on cross-stack explanation, readiness,
comparison, handoff, and lineage around heterogeneous lab practice.
