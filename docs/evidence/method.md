# Evidence Method

## Status

Ready evidence-method owner.

This document owns interpretation rules for evidence rows. It is not the
evidence inventory, product vision, research index, journey owner, or
architecture decision.

## Purpose

Keep [`inventory.md`](inventory.md) focused on evidence IDs, pain rows,
top-level pains, candidate `JC` rows, anti-patterns, and saturation. Use this
document to interpret source confidence, bias correction, source handling, and
promotion hygiene.

## Bias Correction

Treat source families separately:

- Fricon predecessor lessons are useful evidence, but over-emphasize
  measurement history and stable reopen.
- The workflow improvement case adds current friction around notebooks, copied
  code, parameter and registry files, wiring sheets, generated artifacts,
  derived arrays, environment coupling, and report handoff.
- Historical automation discussion is low-confidence design pressure, not
  source evidence or accepted subsystem order.
- Blind persona and capability-gap role-play are prompt-method checks, not user
  research.
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
| Evidence-backed inference | Reasoned conclusion supported by multiple observations. | Candidate for journey selection or narrow promotion. |
| Latent pressure | Plausible pain hidden by the old workflow's limits. | Preserve with source and validation route; do not treat as accepted scope. |
| Hypothesis | Plausible product shape, UX, ordering, or API. | Keep out of accepted scope until journey validation. |
| Future pressure | Likely later capability pressure. | Preserve room for it; do not implement from inventory alone. |
| ADR-gated | Mutation, compatibility, storage, distributed, remote, safety, or AI-action risk. | Requires explicit decision before acceptance. |

## Source Support

Support strength is claim-level support only. It does not mean a pain is urgent,
ready for an early slice, or especially high leverage.

Read source support as two axes:

- source family: predecessor lessons, workflow improvement case, user context,
  blind persona check, external references, or low-confidence design pressure;
- claim handling: observation, inference, latent pressure, engineering
  guardrail, assumption, future pressure, or ADR-gated decision.

When the evidence table uses compact labels such as `engineering guardrail` or
`assumption`, those labels describe claim handling rather than empirical source
families.

## ID Rules

Inventory IDs are stable cross-document references:

- `EV-###` for evidence items;
- `PN-###` for pain points;
- `TP-###` for top-level pain narratives;
- `JC-###` for journey candidates.

After an ID is referenced from another document, do not renumber it. Add a new
ID instead.

## Pain Selection Rubric

Pain order is direction-bias corrected for selecting the next journey. It is
based on:

- workflow improvement case signal density;
- Scopecat leverage without claiming authoritative ownership of opaque files;
- ability to validate the pain without device control, write-back, or broad
  managed execution;
- pain visibility, so directly observed artifact pain does not crowd out latent
  workflow pressure created by the old system's limits;
- fit with a thin vertical journey that can still preserve future platform
  composition.

IDs remain stable. Table order may change as new evidence arrives.

## Statement-Kind Separation

The `PN` prefix is a stable cross-reference for pain-shaped pressure. It is
not enough by itself for journey selection. Some rows are natural
decompositions of top-level pains; some are adoption guardrails; some are
jobs-to-be-done candidates; some are capability gaps; and some are expected
measurement-framework baseline behavior.

Use this separation as a thinking aid, not as a rigid taxonomy. A row may have
secondary roles, and a future journey can override the classification if it
records why.

| Statement kind | Meaning | Journey-selection handling |
| --- | --- | --- |
| Foundational pain | A user-facing inability, risk, or costly workaround that naturally decomposes a `TP` narrative. | Can become acceptance pressure for a journey after evidence and boundary checks. |
| Adoption blocker or guardrail | A reason users or maintainers would reject the tool even if the main journey looks useful. | Constrain the journey; do not automatically turn into feature scope. |
| JTBD candidate | A situational job that should be phrased as "when..., help me..., so I can..." in a journey. | Convert into current-state and future-state journey text before implementation planning. |
| Capability gap | A desired system capability that existing measurement/control frameworks cover weakly, locally, or only in controlled stacks. | Use for differentiation only when tied back to a top-level pain, evidence, and a fixture. |
| Existing-framework baseline or validation case | Behavior users may reasonably expect from mature measurement/data systems, or a technical case needed to validate a model. | Treat as substrate, fixture, acceptance detail, or non-differentiating capability; do not present as the product's main pain. |

Execution records should separate executor status from scientific or analysis
status. A task can run successfully while a health check, fit score, or quality
gate asks for review. Do not collapse these into one lifecycle state unless a
journey explicitly defines that contract.

Journey selection should distinguish pain from JTBD explicitly. A pain can be:

```text
I cannot tell which code and context are safe to use on this control computer,
in an inherited bundle, or on a screening setup, so I copy a working bundle
before using it.
```

A corresponding JTBD should be more situational:

```text
When I need to reuse a protocol on a screening setup, or check an inherited
bundle against a known-good reference, help me compare code, environment,
selected context, setup assumptions, calibration, and generated artifacts, so I
can decide what must be checked before spending experiment time.
```

The JTBD is the shape of a journey. The pain explains why the journey matters.
The capability describes what the system must do. The baseline states what a
reasonable measurement/data system is already expected to provide.

## Updating Evidence

When evidence changes, use these prompts to keep the docs coherent without
turning evidence work into form-filling:

- If a new row changes a journey candidate, update the candidate's evidence
  posture or boundary in [`inventory.md`](inventory.md).
- If a source is messy, biased, generated, or historical, preserve the useful
  pressure and label its class instead of either deleting it or over-promoting
  it.
- If a classification does not fit the table above, write the local judgment in
  the owning row rather than inventing a new taxonomy.
- If a prompt, role-play, or blind review produces a good idea, tie it to
  source evidence or mark it as latent pressure before it influences scope.
- If a discussion introduces a solution-shaped concept such as code registry,
  managed runner, automatic version management, proposal workflow, runtime
  handoff, or universal metadata, first recover the user-visible pain that made
  the concept attractive. Keep the concept as a capability hypothesis until a
  fixture or user validation proves that the smaller pain-focused path is not
  enough.
- If the pain is caused by code or execution fragmentation, distinguish the
  minimum useful integrated support from a full runtime product. For example,
  selecting a previous code version for a bounded local run may be a real user
  workflow, while automatic dependency closure, isolated process management,
  code registries, restart supervision, leases, and replacement of an existing
  control stack remain separate capability hypotheses.

## Source Handling Guardrails

- Treat LabRAD, Data Vault numeric IDs, `idx` filenames, latest-file lookups,
  local counters, and local folder conventions as source conventions and
  validation fixtures, not product concepts.
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
  setup ontology in early journey work.
- Require manual setup or topology maintenance to earn its keep through lookup,
  calculation, visualization, comparison, handoff, or diagnostics.
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
  previous pain inventory in the prompt;
- do not promote generated pains unless they map to foundational pains with
  visibility, source coverage, and a validation route.

## Decision Source Hygiene

Some constraints come from repository process rather than lab-user pain. Keep
them in their lane.

| Source of pressure | Valid use | Do not convert into |
| --- | --- | --- |
| Public-docs redaction rules | Redact public docs and exports; treat local identifiers as portability and reuse evidence. | A product requirement for internal redaction workflows without user evidence. |
| Research extraction policy | Keep raw input, extracted claims, and promoted decisions separate. | A visible product extraction workflow. |
| Durable-doc ownership policy | Put accepted facts in the smallest owning project doc. | A product information architecture or database model. |
| Journey-first docs policy | Delay capability/spec promotion until a concrete journey explains the need. | Proof that the first route must follow tracker order. |
| Legacy workflow conventions | Use as current-state evidence and validation fixtures. | Features that preserve fragile old workflows as preferred behavior. |
| Engineering safety reasoning | Mark mutation, compatibility, storage, remote execution, and AI action as ADR-gated. | User pain unless tied back to workflow evidence. |

## Design Pressures

Historical discussions and predecessor work preserve useful pressures that a
run-history-only product would miss. Use these as journey-selection prompts,
not as accepted subsystem names:

| Design pressure | Evidence and pain support | Why preserve it |
| --- | --- | --- |
| Run and bundle evidence | EV-001, EV-002, EV-003, EV-010, EV-016; PN-001, PN-015 | Useful anchor for identity, data, lifecycle, and context, but not enough by itself to differentiate Scopecat. |
| Scan semantics and preview | EV-010, EV-016, EV-019, EV-021, EV-024; PN-012, PN-017 | Pre-run plan pressure needs representation before device apply or workflow orchestration. |
| Settings, calibration, and context evidence | EV-004, EV-005, EV-015, EV-043; PN-002, PN-003, PN-014, PN-032 | Current files create source-of-truth ambiguity; start with candidate states, local schemas, prior-version retry, branch/working-point history, bad-state exclusion, and advisory proposed values, without accepting a proposal workflow or write-back route. |
| Code and dependency provenance | EV-006, EV-008, EV-021; PN-006 | Code identity is separate from execution. |
| Setup and runtime boundary evidence | EV-011, EV-037, EV-041, EV-042; PN-008, PN-028, PN-031 | Setup context is real, but live control and leases require validation and safety decisions. |
| Execution readiness and lifecycle evidence | EV-007, EV-021, EV-023, EV-024, EV-026, EV-027, EV-031, EV-032; PN-005, PN-016, PN-018, PN-022, PN-025 | Readiness, helper-authored grouped calibration intent, review gates, requested next action, known-good references, failure policy, and outcome records matter before schedulers, managed runners, or environment mutation. Minimal local execution still needs observed transcript evidence before it becomes accepted scope. |
| Cross-journey handoff and lineage | EV-009, EV-017, EV-018, EV-019, EV-022, EV-025, EV-028, EV-029, EV-030, EV-033, EV-044, EV-045; PN-004, PN-010, PN-011, PN-012, PN-019, PN-020, PN-021, PN-023, PN-024 | Derived results, corrections, run families, reports, handoff, false-confidence risk, and data-shape validation guide vertical journey selection. |

## External Baseline Rule

Use [`external-baseline.md`](external-baseline.md) as a differentiation
baseline, not as competitive claims. Mature systems already cover many
acquisition, metadata, instrument, scheduler, and calibration concerns.
Scopecat's gap should stay focused on cross-stack explanation, readiness,
comparison, handoff, and lineage around heterogeneous lab practice.
