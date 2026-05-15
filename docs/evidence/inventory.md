# Evidence And Pain-Point Inventory

## Status

Ready as evidence owner. The first fixture boundary and journey-selection
decision are now promoted to
[`../journeys/jc-001/selection.md`](../journeys/jc-001/selection.md).

## Purpose

Own evidence for promoted journeys and future journey selection.

This document is not a product vision, persona definition, capability map, or
architecture decision. It exists to make later journey and vision work less
volatile by separating:

- observed facts and source evidence;
- evidence-backed inferences;
- plausible but unaccepted product bets;
- ADR-gated or explicitly deferred directions.

Legacy workflows are current-state evidence. They are not automatically
workflows Scopecat should preserve, encourage, or emulate.

Project-level product direction and adoption boundaries are owned by
[`../strategy/vision.md`](../strategy/vision.md). Phase and coordination status are owned by
[`../status/progress-tracker.md`](../status/progress-tracker.md). `JC-###`
folders own journey-specific scope. This inventory owns evidence, stable
EV/PN/TP IDs, support levels, and validation routes.

## Historical Journey Quick Start

Use this document as the evidence owner behind the first promoted journey. `JC-001`
has been promoted into the first slice document set under
[`../journeys/jc-001/README.md`](../journeys/jc-001/README.md), and the short
journey-selection note is
[`../journeys/jc-001/selection.md`](../journeys/jc-001/selection.md).

- Promoted first candidate: `JC-001`, explaining an existing run or work bundle
  with selected context, code provenance, dependency readiness, companion
  artifacts, and ambiguity.
- Primary acceptance pressure for that journey: `PN-002`, `PN-006`,
  `PN-005`, and `PN-001`.
- Primary constraints: adoption-risk hypotheses and guardrails `PN-020`
  through `PN-025`, plus portability and low-ceremony constraints from `PN-007`
  and `PN-016`.
- Diagnostic sharing is boundary-aware: internal lab diagnostics should preserve
  useful local context by default, while public docs, external exports, or
  explicit cross-boundary support packages need sanitization or redaction.
- Historical selection work: the first fixture-boundary and journey-selection
  pass has already been promoted. Future fixture or journey changes should
  update the `journeys/jc-001/` document set instead of reopening this
  inventory as active scope.
- `JC-009` and `JC-010` remain sanity-check alternatives for later
  diagnostic/comparison journeys, not rollback, environment management,
  scientific-equivalence scoring, or device-control scope.
- Do not promote broad project boundaries from evidence alone. Use
  [`../strategy/vision.md`](../strategy/vision.md) for current project-level
  default nonrequirements, and use journey documents for
  fixture-specific exclusions.

For row interpretation, keep the statement kind separate from the stable ID:
foundational pains can drive acceptance, adoption-risk hypotheses and guardrails
constrain the journey after validation checks, JTBD candidates need journey
phrasing, capability gaps need fixtures, and framework baselines are substrate
or validation detail rather than primary product pain.

## Sources

- [`research/extracted/research-acceptance-readiness-triage.md`](research/extracted/research-acceptance-readiness-triage.md)
- [`research/extracted/experimental-lab-workflow-reference.md`](research/extracted/experimental-lab-workflow-reference.md)
- [`research/greenfield-experimental-automation-architecture-notes.md`](research/greenfield-experimental-automation-architecture-notes.md)
- [`research/raw/fricon-legacy-docs/README.md`](research/raw/fricon-legacy-docs/README.md)
- workflow improvement case code tree, cited only as an internal source family.
  Do not cite its old local folder name as a product concept; it is a real
  improvement case, not a generic sample app.
- user-supplied generic lab context, cited only as non-public contextual input.
- blind role-play brainstorm using only generic lab context and no repository
  documents, cited as adoption-risk pressure rather than validated user
  research.
- blind A/B role-play comparison with and without behavioral and scaling priors,
  cited only as prompt-method evidence and latent-pain generation pressure.
- public documentation for existing experiment measurement, control, data, and
  calibration frameworks, cited as external capability baseline rather than as
  exhaustive competitive analysis.

The legacy code sample is internal research evidence. Public documents must
redact local paths, machine details, instrument addresses, local users, and
lab-specific identifiers, but the primary internal concern is portability:
hard-coded local context should not become required for reuse.

## Lab And User Context

This context is common enough for internal product discovery, but it is still not
a persona, market definition, or accepted product requirement. Use it to explain
why portability, low ceremony, same-setup readiness, bounded cross-setup
trust, and technical-owner boundaries matter during journey selection.

- A lab may have multiple equipment systems that are similar in purpose but not
  identical in instruments, drivers, wiring, calibration state, local files, or
  machine setup.
- Some scientifically important context cannot be verified from software alone,
  or can only be weakly cross-checked: actual physical wiring, switch paths,
  mounted sample identity, sample or chip topology, line attenuation, and how
  qubits, gates, channels, and instruments correspond in practice.
- One equipment station may include multiple computers, but usually one Windows
  computer is the effective instrument-control machine.
- For a given experiment plan and researcher, routine work on one sample usually
  stays on the same equipment system. Do not assume that the same sample
  normally moves across equipment groups.
- Cross-system pressure is clearest when the same or similar protocol is used
  to screen multiple samples on several non-identical equipment and computer
  stacks. Setup bring-up, handoff, and known-good comparison can be same-setup
  or cross-setup and should be classified by the fixture.
- Most users can write experiment scripts and plot or analyze data, but they do
  not want to spend scarce experiment time on environment repair, configuration
  archaeology, driver issues, or file organization.
- A smaller technical-owner group maintains devices, drivers, control computers,
  helper packages, and operational conventions. Their work shapes what ordinary
  experiment users can safely rely on, but it should not force every user into a
  managed framework.
- Data acquisition, quick inspection, deeper analysis, reporting, and method
  maintenance may happen on different machines or by different people, which
  makes source identity and portable handoff more important than local folder
  conventions.
- Users often find high-value data through experiment names, measurement-object
  labels, quick plots, and simple favorite/star marks.
- Moving code or methods between experiment-control computers is a different
  case from analysis handoff. Early unmanaged workflows may still copy whole
  code folders. Setup, parameter, and machine-specific context from one control
  computer usually needs review and adjustment before it is useful on another
  control computer.
- Lab membership, projects, and sample ownership change over time. Handoffs may
  happen while an experiment is still active, a sample is still being measured,
  or the code and calibration workflow are still changing.
- Tacit experiment knowledge often lives in notebooks, copied folders, comments,
  file names, local scripts, chat messages, oral explanation, and personal
  memory. New users inherit not only final methods, but also failed attempts,
  debug traces, temporary fixes, and half-migrated conventions.
- Experiment time can be scarce because of cooldowns, equipment schedules,
  sample state, and shared systems. Users need problems in code, configuration,
  environment, and handoff packages to surface before the valuable measurement
  window when possible.
- Manual maintenance of physical setup, chip topology, or experiment-schema
  records is only attractive when it creates visible value: looking up the
  instrument or channel for a qubit, calculating line attenuation, visualizing
  qubit and gate parameters on a chip layout, comparing setup variants, or
  preparing a handoff. Otherwise it risks becoming stale clerical work.
- Experiment parameter schemas and physical-configuration models are difficult
  to predefine across all experiments. They often evolve with samples, chip
  designs, methods, and lab conventions, while remaining approximately stable
  over a bounded campaign or setup period.
- Working control computers are often treated conservatively. Users and
  maintainers may reject tools that require heavy services, network or cloud
  availability, account friction, automatic driver/environment mutation, or
  background behavior that can break a known-good setup.

Journey selection can use this context to validate assumptions behind TP-002, TP-003, TP-005,
TP-006, TP-007, TP-008, TP-009, TP-010, PN-004, PN-005, PN-006, PN-007,
PN-016, PN-018, PN-020 through PN-025, PN-026 through PN-032, and PN-033
through PN-037. It should not promote
Windows support, deployment management, driver maintenance, lab IT
administration, onboarding, training, environment management, rollback
automation, a universal experiment schema, exhaustive lab inventory management,
or a full ELN into early scope unless a journey explicitly needs them.

For the current project-level relationship to existing experiment systems, use
[`../strategy/vision.md`](../strategy/vision.md).

## Direction-Bias Correction

Predecessor project documentation strongly emphasizes its Measurement History
framing and stable reopen. That material is useful evidence, but Scopecat
exists partly to correct the predecessor project's narrowed direction. It
should not be treated as the default source of priority.

The workflow improvement case code tree represents a real current workflow with
observable friction and candidate Scopecat intervention points. It adds a
different center of gravity: notebooks, copied and backup code, parameter and
registry files, wiring spreadsheets, generated protocol artifacts, derived
`.npy`/`.npz`/`.pkl` artifacts, local environment coupling, and report or
presentation handoff bundles. Need, value, and product shape still require journey or user validation.

The automation architecture notes came from a broader attempt to replace
manual-discipline recordkeeping with reliable automatic versioned records and
the workflows that become possible afterward. Their subsystem map may be
premature, but the design pressures behind it should remain visible during journey selection
so Scopecat does not drift back into a run-history-only plan.

A later blind persona brainstorm used the generic lab context but withheld this
repository's docs and pain inventory. Treat it as a source-bias sanity check,
not as user research. Its useful signal is the repeated adoption-blocker shape:
false confidence from partial provenance, a new tool becoming another drifting
source of truth, live control-PC fragility, the need for a known-good reference,
rollback pressure, and precise diagnostics whose sharing boundary is explicit.
Do not read it as evidence that routine same-sample work usually moves across
equipment groups; cross-setup claims need fixture or interview support and are
most plausible for screening, setup comparison, handoff, and protocol-transfer
cases.

A later capability-gap brainstorm used the same blind setup but asked a
different question: not "why would users reject this tool?", but "what desired
capabilities are not provided by common measurement and control frameworks, or
are provided only in narrow ecosystems?" Treat its output as product-opportunity
pressure. It is stronger when it aligns with external framework baselines and
workflow improvement evidence; it is still not proof of market demand.

A later A/B role-play check compared agents that received only generic lab
context with agents that also received behavioral and scaling priors. The priors
improved coverage of partial metadata confidence, copy-forward provenance,
branchy analysis, progressive local schemas, failure localization, calibration
dependencies, and useful manual metadata. They also risked narrowing prompts
toward messy exploratory labs, superconducting-style wiring concerns,
individual rescue workflows, anti-schema bias, and passive capture. Treat this
as a discovery-method result, not as evidence that generated pains are urgent.

evidence pass should therefore separate three judgments that were previously compressed
into one confidence column:

- whether a claim is well supported by evidence;
- which source families support it;
- whether it is a high-leverage Scopecat improvement target.

Pain-point order below is direction-bias corrected for journey selection. It should
not be read as a final product roadmap.

## Behavioral And Scaling Discovery Priors

These priors are not evidence, accepted scope, persona definitions, or product
requirements. Use them to generate role-play prompts, interview prompts,
fixtures, and latent pain hypotheses. A pain generated from these priors can
affect candidate rank only after it is supported by evidence, a fixture, an interview,
a prototype spike, or direct journey acceptance pressure.

| Prior family | Useful prompt pressure | Main narrowing risk |
| --- | --- | --- |
| Scarce experiment time | Users prioritize running experiments over clean records; recording must have same-session value such as recall, comparison, diagnostics, rerun, visualization, or handoff. | Can underweight mature labs where structured entry is accepted because it directly powers automation or compliance. |
| Known-good comparison | Recent working state is often more actionable than abstract documentation; users debug by asking what changed since the last good run. | Can preserve copy-forward habits and underweight cleaner abstractions once a campaign stabilizes. |
| Copy-forward work | Copied folders, scripts, notebooks, and parameter files are low-cognitive-cost risk control and need ancestry, divergence, and abandonment tracking. | Can bias discovery toward legacy rescue rather than greenfield method design. |
| Branchy analysis | Temporary constants, manual exclusions, fit windows, rerun subsets, local scripts, and notebooks often determine conclusions. | Can overemphasize exploratory analysis and underweight disciplined pipeline-heavy labs. |
| Layered failure localization | Failures may come from hardware, drivers, environment, scripts, parameters, sample state, physical setup, operator action, or analysis choice. | Can bias toward maintainer diagnostics and underweight scientist-facing interpretation or collaboration. |
| Declared physical context | Wiring, attenuation, chip topology, aliases, sample state, and physical/logical mappings are important but not software-proven by default. | Can underplay opportunities for instrument discovery, switch-matrix checks, barcode/sample tracking, or other automated validation. |
| Manual metadata ROI | Manual setup, topology, or schema maintenance survives only when it powers lookup, calculation, visualization, comparison, handoff, or diagnostics. | Can discourage useful structured entry before its downstream automation value is demonstrated. |
| Progressive local schemas | Parameter, setup, and topology schemas evolve with samples, methods, and conventions, while remaining locally stable for a campaign or setup period. | Can make the model too loose if journey selection never validates stronger schemas after stability appears. |
| Scaling pressure | More qubits, gates, calibrations, aliases, corrections, and dependencies turn memory and handoff issues into automation blockers. | Can overfit to superconducting-style scale pressures and miss platform-specific pains in other quantum systems. |

When using these priors for blind role-play, keep prompt-method hygiene:

- include at least one no-prior control role for the same question;
- ask prior-informed roles to list which priors helped and which narrowed
  thinking;
- rotate role lenses beyond ordinary operator and maintainer when the question
  involves analysis, handoff, governance, or scale;
- avoid naming the current product, repository documents, local code samples, or
  previous pain inventory in the prompt;
- do not promote generated top-level pains unless they map to foundational
  pains with visibility, source coverage, and validation route.

## Evidence Classes

| Class | Meaning | Handling |
| --- | --- | --- |
| Observation | Directly observed in extracted notes or code-sample review. | Safe to cite as evidence with portability caveats; redact only for public use. |
| Evidence-backed inference | Reasoned conclusion supported by multiple observations. | Candidate for journey selection or narrow promotion. |
| Latent pressure | Plausible pain or opportunity that the legacy workflow may hide because the old system made the better workflow impossible, awkward, or hard to imagine. | Preserve explicitly with source and validation route; do not treat as direct evidence or accepted scope until interviews, fixtures, spikes, or journeys validate it. |
| Hypothesis | Plausible product shape, UX, ordering, or API. | Keep out of accepted scope until journey validation. |
| Future pressure | Likely later capability pressure. | Preserve room for it, but do not implement from evidence pass. |
| ADR-gated | Mutation, compatibility, storage, distributed, remote, safety, or AI-action risk. | Requires explicit decision before acceptance. |

## Claim Support, Source Coverage, And Pain Validation

Support strength is claim-level support only. It does not mean a pain point is
urgent, ready for an early slice, or especially high leverage for Scopecat.

Read source support as two axes:

- source family: predecessor project docs, workflow improvement case, user
  context, blind persona check, external references, or automation architecture
  notes;
- claim handling: observation, inference, latent pressure, engineering
  guardrail, assumption, future pressure, or ADR-gated decision.

When the evidence table uses compact labels such as `engineering guardrail` or
`assumption`, those labels describe claim handling rather than empirical source
families.

| Field | Meaning |
| --- | --- |
| Support strength | How strongly the inventory supports the claim's existence or inference. |
| Source coverage | Which source families and handling labels carry the claim. Do not treat assumptions or engineering guardrails as user evidence. |
| Pain visibility | Whether a pain is directly visible in current artifacts, inferred from missing structure, latent behind constrained workflows, interview-driven, or mostly future/ADR pressure. |
| Validation route | The smallest next check that can strengthen or reject the pain: case fixture, interview prompt, prototype spike, journey acceptance, or ADR. |
| Scopecat leverage | How much the claim appears to expose a useful Scopecat intervention after direction-bias correction. This is handled in pain ranking, not in the evidence table. |

## ID Convention

Inventory IDs are intended for cross-document references. Use stable,
document-owned prefixes:

- `EV-###` for evidence items;
- `PN-###` for pain points;
- `TP-###` for top-level pain narratives that decompose into foundational
  pain points;
- `JC-###` for journey candidates.

After an ID is referenced from another document, do not renumber it. Add a new
ID instead.

## Source Handling Guardrails

- Treat LabRAD, Data Vault numeric IDs, `idx` filenames, latest-file lookups,
  local counters, and local folder conventions as source conventions and
  validation fixtures, not product concepts.
- Use "companion artifact" as the product-neutral term. "Sidecar" is legacy
  evidence vocabulary for colocated or conventionally named files.
- Treat notebooks as current-state workflow spines and provenance evidence.
  Do not infer automatic notebook-state capture from notebook-heavy evidence.
- Treat parameter files, registry files, wiring sheets, generated summaries,
  and setup files as opaque context candidates unless a later model owns their
  semantics.
- Treat physical wiring, mounted sample state, chip topology, line attenuation,
  and alias maps as declared or externally evidenced state unless a later
  validation path exists. Track source, freshness, validity period, and
  verification status instead of presenting them as software-proven truth.
- Prefer local, versioned, evolvable schemas over a universal parameter or
  setup ontology in early journey work. A schema can be useful when it stays stable inside a
  campaign, sample, method, or setup period, even if it is not global.
- Require manual setup or topology maintenance to earn its keep through a
  concrete user-visible job: lookup, calculation, visualization, comparison,
  handoff, or diagnostics. Do not collect high-ceremony metadata only because it
  might be useful later.
- Treat predecessor project documentation's run-history emphasis as one source
  signal, not as the default priority order when the workflow
  improvement case points at configuration, code provenance, generated
  artifacts, or handoff friction.
- Cite predecessor project docs as predecessor evidence, not as a source name
  that defines Scopecat direction. Scopecat exists partly to correct that
  predecessor direction.
- Treat automation architecture notes as capability-pressure evidence and
  vocabulary, not as accepted subsystem boundaries, implementation order, or a
  documentation scaffold.
- Mark counterfactual or workflow-expanding pains as latent pressure when the
  current code tree cannot show them directly because the old system constrained
  the workflow. Use those pains to shape journey-selection questions, interviews, and spikes;
  do not silently upgrade them into high-confidence accepted requirements.
- Keep top-level pain narratives separate from foundational pain points.
  Top-level narratives preserve user-language pressure; foundational pain
  points carry evidence, visibility, validation route, and acceptance boundaries.
- Represent roles as hats or lenses within a journey. Do not split one natural
  lab workflow into separate journeys only because the operator, analyst,
  method author, and configuration reviewer roles appear in the same notebook.
- Surface candidate context, provenance, freshness, and ambiguity. Do not claim
  Scopecat can infer authoritative truth from arbitrary legacy files.
- Treat blind persona outputs as adoption-risk prompts. They are most useful
  when they expose product rejection reasons that existing docs may have
  hidden, but they still need interviews, fixtures, or spikes before changing
  accepted scope.
- Treat behavioral and scaling priors as prompt seeds, not source evidence.
  Preserve no-prior controls when using them for role-play, and record any
  narrowing risks the roles identify.
- Avoid creating a parallel truth store. Early Scopecat records should label
  observed, declared, selected, proposed, applied, missing, stale, and
  unchecked state instead of silently claiming authority over scripts, control
  computers, notes, or existing config files.

## Decision Source Hygiene

Some constraints in this inventory come from repository documentation rules or
agent operating rules rather than from lab-user pain. Keep those rules in their
lane during journey selection.

| Source of pressure | Valid use in early journey work | Do not convert into |
| --- | --- | --- |
| Public-docs redaction rules | Redact public docs and external exports; treat internal local identifiers primarily as portability and reuse evidence. | A product requirement for internal redaction workflows without user evidence. |
| Research extraction policy | Keep raw input, extracted claims, and promoted durable decisions separate. | A claim that users need a visible extraction workflow in the product. |
| Narrow durable-doc ownership policy | Put accepted facts in the smallest owning project doc. | A product information architecture or database model. |
| Journey-first docs policy | Delay capability/spec promotion until a concrete journey explains the need. | Proof that the first product journey must follow the tracker order exactly. |
| No-placeholder-scaffold docs policy | Avoid copying broad subsystem trees before real accepted content exists. | Evidence against modular product architecture when a journey later needs it. |
| Legacy workflow conventions | Use as current-state evidence and validation fixtures. | Features that preserve fragile old workflows as preferred behavior. |
| Engineering safety reasoning | Mark mutation, compatibility, storage, remote execution, and AI action as ADR-gated. | User pain unless tied back to observed workflow evidence. |

## Design Pressure From Automation Notes

The automation architecture notes are useful because they name independently
useful design pressures that a run-history-only product would miss. This table
preserves those intents for journey selection without accepting the notes' subsystem map,
capability names, implementation order, or documentation scaffold.

| Design pressure | Evidence and pain support | Why preserve it now |
| --- | --- | --- |
| Run and bundle evidence | EV-001, EV-002, EV-003, EV-010, EV-016; PN-001, PN-015 | Useful anchor for identity, data, lifecycle, and context, but not enough by itself to differentiate Scopecat from existing measurement systems. |
| Scan semantics and preview | EV-010, EV-016, EV-019, EV-021, EV-024; PN-012, PN-017 | Ad-hoc scan meaning, generated protocol context, and pre-run plan pressure need structured representation before device apply or full workflow orchestration. |
| Settings, calibration, and context evidence | EV-004, EV-005, EV-015, EV-043; PN-002, PN-003, PN-014, PN-032 | Current files create source-of-truth ambiguity; early scope should show candidates, local schema versions, and proposals before any authoritative write-back. |
| Code and dependency provenance | EV-006, EV-008, EV-021; PN-006 | Copied scripts, notebooks, packages, backups, generated bytecode, and lockfile or environment clues make code identity a separate problem from execution. |
| Setup and runtime boundary evidence | EV-011, EV-037, EV-041, EV-042; PN-008, PN-028, PN-031 | Setup and device context are real, but declared physical facts, live control, apply semantics, and leases require later validation and safety decisions. |
| Execution readiness and lifecycle evidence | EV-007, EV-021, EV-023, EV-024, EV-026, EV-027, EV-031, EV-032; PN-005, PN-016, PN-018, PN-022, PN-025 | Environment readiness, execution packages, known-good references, failure policy, and run records matter before accepting schedulers, queues, remote execution, or automatic environment mutation. |
| Cross-journey handoff and lineage | EV-009, EV-017, EV-018, EV-019, EV-022, EV-025, EV-028, EV-029, EV-030, EV-033, EV-044, EV-045; PN-004, PN-010, PN-011, PN-012, PN-019, PN-020, PN-021, PN-023, PN-024 | Derived results, generated protocols, corrections, run families, reports, campaign-level questions, personnel handoff, truth-drift risk, false-confidence risk, support diagnostics, high-value run selection, and data-shape validation cross product-value routes and should guide vertical journey selection. |

## External Framework Capability Baseline

This section is a baseline for differentiation, not a claim that any framework
is weak, unsuitable, or directly comparable to Scopecat. The selected public
docs suggest that mature systems already contain strong answers for measurement
execution, run data, metadata, instrument abstraction, real-time control,
scheduling, and specialized calibration workflows. Scopecat should therefore
avoid positioning ordinary run history, instrument drivers, or a generic runner
as the whole advantage. Treat the rows as illustrative baselines, not a
market map or exhaustive competitive analysis.

| External baseline | What it already covers | Scopecat gap pressure |
| --- | --- | --- |
| [QCoDeS](https://microsoft.github.io/Qcodes/examples/basic_examples/15_minutes_to_QCoDeS.html) | Python instrument parameters, measurement loops, datasets, experiment/sample metadata, and station/instrument snapshots. | Do not compete by merely saving run metadata or instrument snapshots; focus on selected context, code provenance, same-setup readiness, bounded protocol-transfer readiness, and legacy bundle explanation around existing scripts. |
| [Bluesky Event Model](https://blueskyproject.io/event-model/main/explanations/data-model.html) | Documented run/event schemas for data and metadata, event descriptors, run start/stop records, streaming, and callbacks. | Treat event/run records as a proven pattern, but preserve gaps around notebooks, generated artifacts, physical setup reality, handoff bundles, and scientific comparability outside one controlled stack. |
| [Keysight Labber](https://www.keysight.com/us/en/assets/3122-1301/technical-overviews/M5401LxxA-Labber.pdf) | Commercial instrument server, measurement editor, log browser, Python API, and quantum-measurement-oriented automation. | Do not assume users lack measurement GUIs or log browsers; emphasize low-intrusion explanation, comparison, and handoff for labs that already have local tools and copied scripts. |
| [labscript BLACS](https://docs.labscriptsuite.org/projects/blacs/en/latest/shot-management/) | Shot queues, connection-table compatibility checks, hardware programming flow, error handling, and analysis forwarding in that ecosystem. | Hardware compatibility checks are a known valuable pattern; Scopecat's early version should remain diagnostic and evidence-based across existing setups rather than claiming device-control authority. |
| [ARTIQ](https://m-labs.hk/artiq/manual/introduction.html) | Quantum experiment control, nanosecond-timing hardware execution, scheduling, GUIs, result visualization, and Windows/Linux availability. | Do not frame Scopecat as a replacement for real-time control systems; frame it as a provenance, readiness, comparison, and handoff layer around heterogeneous lab practice. |
| [Qiskit Experiments calibration management](https://qiskit-community.github.io/qiskit-experiments/stable/0.5/apidocs/calibration_management.html) and [Qibocal runcards](https://qibo.science/qibocal/stable/getting-started/runcard.html) | Specialized calibration schedules, parameter values, calibration experiments, declarative calibration runcards, and protocol libraries. | Calibration routines exist in specialized stacks; Scopecat's gap is cross-stack calibration context, dependency impact, proposal review, and downstream result/analysis trust. |
| [LabRAD](https://sourceforge.net/p/labrad/wiki/Introduction/) | Distributed modular instrument control and data acquisition/management for heterogeneous experimental setups. | Distributed modular control is an established approach; Scopecat should first complement existing distributed or local systems with explainability, diagnostics, and migration evidence. |

The repeated gap is not "no one stores measurements." The repeated gap is that
existing systems usually cover one controlled execution or data ecosystem better
than they cover an inherited, Windows-heavy, multi-system lab workflow where
scientific meaning depends on copied code, notebooks, manual interventions,
calibration state, physical setup reality, and analysis lineage.

## Visibility Bias And Evidence Gaps

The workflow improvement case is strong at exposing artifact, provenance,
configuration, environment, and handoff failures. It is weaker at exposing pains
for workflows the old system never made practical: previewable plans,
pre-execution review, trusted execution packages, campaign-level comparison,
resource coordination, and automation that depends on reliable versioned
records.

Treat that weakness as visibility bias, not disproof.

| Area | Current evidence pass balance | Evidence worth supplementing | Pain worth testing |
| --- | --- | --- | --- |
| Selected context and provenance | Strong direct evidence from files, notebooks, copied code, generated artifacts, and local conventions. | Exact source bundle with selected context, code, generated artifacts, derived outputs, and ambiguity examples. | Whether passive explanation is enough for the first slice, or whether users need review/freeze semantics immediately. |
| Scan semantics and preview | Evidence exists, but the pain is mostly phrased as later reproducibility rather than pre-run control. | Existing scan loops, generated protocol files, intended parameter spaces, dry-run-like helper outputs, and places where users manually inspect the plan. | Whether users need to preview, diff, freeze, or approve a plan before hardware execution. |
| Parameter memory and calibration | Strong evidence for source-of-truth ambiguity and mutation risk. | Before/after parameter snapshots, calibration proposals, rollback targets, and operator review notes where available. | Whether proposal and review value appears before any write-back or durable parameter owner exists. |
| Managed execution and dry run | Environment readiness is visible; execution package and remote validation are mostly latent. | Logs, status files, dependency manifests, entrypoints, expected artifacts, failures, and handoff packages for rerun attempts. | Whether users need a trusted package that can be validated before execution. |
| Run families and campaigns | Strong lineage examples exist, but cross-run questions are under-specified. | Multi-round recipes, feedback records, correction branches, selected run ranges, and campaign summaries. | Whether users need concept-shaped campaign navigation beyond file-shaped recovery. |
| Handoff and publication | Good evidence for derived artifacts and source identity loss; user-context pressure makes analysis handoff from control computer to personal analysis computer a high-priority adoption case. | Reports, figures, spreadsheets, decks, analysis-ready data packages, run names, star/favorite marks, quick previews, fit-result tables, read API expectations, legacy data-shape validation cases, and the missing links back to run, context, code, correction, and decision records. | Whether analysis handoff should be a follow-on journey after bundle identity, or part of the first fixture; public/reference sharing may need curated analysis datasets plus provenance summaries rather than complete work-bundle export. Reader/API/UI/schema details should wait until an analysis-handoff or durable-record journey is selected. |
| Personnel transition | Generic lab context is strong; current artifact evidence is indirect. | Examples where inherited notebooks, folders, reports, or scripts cannot explain active/obsolete status, intent, or required context. | Whether taking over an old experiment needs its own journey seed, or can be handled through bundle identity and handoff fixtures. |
| Adoption trust and control-PC risk | Blind persona pressure is useful but unvalidated; current artifact evidence is indirect. | Examples where a tool record would drift from scripts or notes, where a control PC cannot tolerate extra services, or where a known-good setup must be restored after a change. | Whether an early journey needs explicit false-confidence, read-only companion, boundary-aware diagnostic, known-good reference, or rollback checks before any managed execution story. |
| Capability gaps beyond common measurement frameworks | External baseline is strong for known framework coverage; workflow improvement and blind capability-gap brainstorm support the remaining gap. | Public-framework comparison notes, sample-screening comparability examples, known-good full-stack diffs, setup alias histories, manual-intervention records, useful declared setup/topology examples, schema-evolution examples, and analysis impact examples. | Whether Scopecat's first slice should explicitly test scientific comparability, full-stack change explanation, setup-reality mapping, useful declared context, schema evolution, or analysis-impact lineage rather than only run reopen. |
| Discovery-prior generated pains | A/B role-play suggests priors improve breadth, but the current artifact evidence is indirect. | Side-by-side no-prior and prior-informed role-play outputs, plus fixtures that test known-good comparison, copy-forward provenance, partial metadata confidence, branchy analysis, failure localization, progressive local schema, and calibration dependency pressure. | Which generated pains are automation blockers rather than nice-to-have, and which are prompt artifacts caused by the priors. |
| Instrument/resource coordination | Setup context is visible; shared-resource coordination is mostly future/ADR pressure. | Concrete cases of concurrent use, lease failures, setup diagnostics, and operator coordination if available. | Whether a minimal lease or resource manifest is useful before device control scope. |

## Evidence Inventory

| ID | Claim | Class | Support strength | Source coverage | Evidence | Affected journeys |
| --- | --- | --- | --- | --- | --- | --- |
| EV-001 | Measurement identity is scattered across Data Vault paths, numeric IDs, notebooks, companion artifacts, copied parameter files, and local naming conventions. | Observation | High | predecessor project docs; workflow improvement case | Extracted research plus workflow improvement case notebooks, `idx` exports, parameter copies, and local naming conventions. | Reopen a run with companion artifacts; recover latest-ID ambiguity. |
| EV-002 | Companion artifacts are part of result meaning, not incidental files. | Evidence-backed inference | High | predecessor project docs; workflow improvement case | `.npz`, `.json`, `.npy`, `.pkl`, copied parameter snapshots, feedback records, figures, spreadsheets, and decks recur beside primary data. | Reopen a run with companion artifacts; publish or hand off analysis. |
| EV-003 | Stable reopen by dataset ID is necessary but insufficient for explainability. | Evidence-backed inference | High | predecessor project docs; workflow improvement case | Numeric IDs and `idx` files reopen raw data, but analysis also needs parameter snapshots, readout correction, generated artifacts, selected run ranges, and notebook-local constants. | Reopen a run with companion artifacts; explain settings for a historical run. |
| EV-004 | Mutable parameter and setup files create uncertainty about source of truth. | Observation | High | workflow improvement case; predecessor project docs | Parameter JSON, registry JSON, wiring sheets, spectro-bias CSVs, generated temp JSON, backups, and lock files coexist. | Explain settings for a historical run; review calibration before mutation. |
| EV-005 | Calibration workflows already mix measurement evidence, fits, operator judgment, and direct settings mutation. | Observation | High | workflow improvement case; predecessor project docs | Calibration notebooks and scripts fit values, compare outputs, then write JSON fields or registry-like fields. | Review calibration before mutation. |
| EV-006 | Code provenance is folder-copy based and ambiguous. | Observation | High | workflow improvement case; predecessor project docs | Duplicated modules, backups, zip snapshots, embedded Git folders, copied packages, checkpoints, generated bytecode, and old script variants coexist. | Clean notebook/run provenance; copied scripts to code asset reference. |
| EV-007 | Local runtime, dependency, and compatibility readiness is a distinct pain from instrument-control semantics. | Evidence-backed inference | High | workflow improvement case; predecessor project docs | Imports and workflows depend on local LabRAD, private helper packages, driver packages, local paths, environment-specific warnings, network-visible resources, and pinned machines. | Can I run this here; local script to managed execution record. |
| EV-008 | Notebooks are important operational artifacts but poor automatic first slice capture targets. | Evidence-backed inference | High | workflow improvement case; predecessor project docs | Many notebooks have uncleared output, execution counts, path-specific code, manual selected IDs, branchy analysis, plots, and checkpoint or backup copies. | Clean notebook/run provenance; publish or hand off analysis. |
| EV-009 | Analysis handoff is a distinct workflow from acquisition. | Evidence-backed inference | High | workflow improvement case; predecessor project docs | Raw IDs, summary CSV/NPY files, tomography/QPT code, figure notebooks, PDFs, spreadsheets, and decks form handoff bundles. | Publish or hand off analysis. |
| EV-010 | Dataset shape pressure is broader than regular grids. | Observation | High | workflow improvement case; predecessor project docs; external references | Evidence includes regular grids, partial grids, traces, shot arrays, IQ data, complex values, probability columns, tomography tensors, feedback records, and ragged derived records. | Reopen a run with companion artifacts; dataset concept work. |
| EV-011 | Hardware bring-up and setup/device context are real evidence, but control and apply semantics cross safety and mutation boundaries. | Evidence-backed inference | High | workflow improvement case; engineering guardrail | Wiring spreadsheet to registry to instrument-driver connection appears as a workflow, with setup diagnostics, physical addresses, live output state, stop/clear commands, offsets, powers, frequencies, timestamps, and calibration artifacts. | Validate hardware bring-up. |
| EV-012 | Measurement lifecycle evidence is richer than partial/interrupted state. | Evidence-backed inference | Medium | predecessor project docs; external references; weak workflow improvement case support | Predecessor project documents describe finished, interrupted, failed, invalidated, corrected, correction history, and lightweight outcome/trust labels; workflow improvement case evidence mostly shows cleanup/debug traces. | Ordinary Python script to durable measurement record. |
| EV-013 | Local identifiers and hard-coded context create portability and reuse pressure. | Evidence-backed inference | High | workflow improvement case; predecessor project docs; engineering guardrail | Local paths, machine/service details, instrument addresses, lab-specific labels, notebook output, generated caches, and reports are intermingled. Public export adds redaction pressure, but internal reuse is mostly blocked by hard-coded context. | Reuse or share a run safely; publish or hand off analysis. |
| EV-014 | Existing external systems support useful background checks but do not settle Scopecat's model. | Observation | Medium | external references | QCoDeS, LabRAD, Bluesky/Tiled, Labber, ARTIQ, and related systems show recurring concerns around runs, datasets, lifecycle, events, snapshots, export, and callbacks. | Capability and architecture validation. |
| EV-015 | Effective configuration selection is more specific than finding a file. | Evidence-backed inference | High | workflow improvement case; predecessor project docs | Dated parameter files, registry backups, lock files, wiring sheets, generated line/chip summaries, temporary companion artifacts, and database-like helpers coexist; users need selected-state records plus ambiguity or staleness warnings. | Explain settings for a historical run; review calibration before mutation. |
| EV-016 | Analysis often reconstructs scan meaning from weak external conventions. | Observation | High | workflow improvement case; predecessor project docs | Plotting and analysis infer shape from column order, filename conventions, sorted rows, companion artifacts, notebook-local arrays, selected run ranges, and manual reshaping. | Reopen a run with companion artifacts; dataset concept work. |
| EV-017 | Readout, SPAM correction, and classifier choices are first-class lineage for some results. | Observation | High | workflow improvement case; predecessor project docs | Feedback, tomography, fidelity, and classifier workflows depend on readout matrices, correction branches, IQ references, classification centers, shot grouping, detector/observable formatting, retraining notes, and manual inspection flags. | Advanced lineage validation; publish or hand off analysis. |
| EV-018 | Some workflows are run families rather than single runs. | Observation | High | workflow improvement case; predecessor project docs | Base dataset IDs plus strides, rounds, init states, measurement probabilities, VZ scans, sequence indices, and per-round JSON/NPY records are needed to interpret results. | Advanced lineage validation; navigate run families. |
| EV-019 | Generated protocol or design artifacts affect reproducibility. | Evidence-backed inference | High | workflow improvement case; predecessor project docs | Random lists, RB lookup tables, generated circuit JSON/PKL, backend qubit maps, measurement basis metadata, and per-sequence files recur beside raw data. | Advanced lineage validation; clean notebook/run provenance. |
| EV-020 | Persistence workarounds indicate durability and source-of-record anxiety. | Evidence-backed inference | Medium | predecessor project docs; workflow improvement case | Legacy helpers include Data Vault bypass, CSV overwrite, and local export flows after creating records, with comments or code paths about avoiding data loss or display mismatch. | Reopen a run with companion artifacts; understand incomplete runs. |
| EV-021 | Method authors are a distinct source of evidence and adoption friction. | Evidence-backed inference | High | workflow improvement case; predecessor project docs | Scan helpers, pulse rules, runner integrations, plotting utilities, report/export recipes, and generated routines are maintained by authors and then run by others who may not understand every dependency. | Low-ceremony Python adoption; copied scripts to code asset reference. |
| EV-022 | Export and handoff need portability, integrity, and source identity. | Evidence-backed inference | Medium | predecessor project docs; workflow improvement case; engineering guardrail | Predecessor project documents name export pressure; workflow improvement case spreadsheets, decks, figures, derived arrays, and local context show handoff bundles whose source identity is easy to lose. | Publish or hand off analysis; clean or share a run safely. |
| EV-023 | Low-ceremony Python adoption is part of the pain evidence. | Evidence-backed inference | Medium | predecessor project docs; workflow improvement case | Interview synthesis centers ordinary Python scripts, notebooks, small recording-section rewrites, stable-ID copy, and avoiding a new managed framework; workflow improvement case confirms ordinary Python/notebook gravity but not the exact product preference. | Run/reopen with context; local product readiness. |
| EV-024 | Current artifacts under-represent prospective control pains because the old workflow has no durable plan, preview, freeze, review, or dry-run object to leave evidence behind. | Latent pressure | Medium | automation architecture notes; workflow improvement case; assumption | Automation architecture notes emphasize automatic versioned records and later workflows that depend on them; workflow improvement case shows scan loops, generated protocols, parameter files, and copied code, but not a reliable pre-execution package lifecycle. | Preview a scan plan; validate a run package before execution; review calibration before mutation. |
| EV-025 | Reliable automatic versioned records would likely enable cross-run, campaign, handoff, and automation questions that legacy file-shaped evidence cannot fully express. | Latent pressure | Medium | automation architecture notes; workflow improvement case; predecessor project docs | Run families, corrections, generated artifacts, handoff bundles, and run-history pressure imply value beyond reopen, but current artifacts do not prove the exact future UX or priority. | Navigate campaigns; compare runs; publish or hand off analysis; define adoption ladders. |
| EV-026 | Multi-system, Windows-heavy lab context strengthens same-setup readiness and bounded protocol-transfer pressure. | Evidence-backed inference | Medium | user context; workflow improvement case; engineering guardrail | Generic lab context includes multiple non-identical equipment systems and one effective instrument-control computer per station. Routine same-sample work usually stays on one setup. Same-protocol sample screening can cross non-identical equipment and computer stacks; setup bring-up, handoff, and known-good comparison may be same-setup or cross-setup depending on the fixture. | Same-setup readiness; sample-screening protocol transfer; clean or share a run safely; validate a run package before execution. |
| EV-027 | Technical ownership is unevenly distributed across ordinary experiment users and a smaller maintainer group. | Evidence-backed inference | Medium | user context; workflow improvement case; predecessor project docs | Most users can write scripts and analyze data, while fewer users maintain devices, drivers, control computers, helper packages, and operational conventions. | Low-ceremony Python adoption; managed execution readiness; setup manifest or diagnostic records. |
| EV-028 | Personnel turnover and short handoff windows make tacit experiment knowledge fragile. | Evidence-backed inference | Medium | user context; workflow improvement case; predecessor project docs | Generic lab context includes project turnover, active experiments inherited midstream, and knowledge spread across notebooks, copied folders, file names, comments, reports, oral explanation, and personal memory. Workflow improvement evidence shows many artifact types whose intent and active/obsolete status are hard to recover. | Take over an old experiment; publish or hand off analysis; navigate campaigns; explain a run or work bundle. |
| EV-029 | A workflow tool can create new truth drift if its records diverge from scripts, control computers, notes, and existing config files. | Latent pressure | Medium | blind persona check; workflow improvement case; engineering guardrail | Blind persona roles repeatedly rejected a tool that becomes another separate source of truth. Workflow evidence already shows parameter, registry, wiring, generated settings, notebook, and backup copies drifting from one another. | Explain a run or work bundle; parameter snapshot; dry-run package validation. |
| EV-030 | Software provenance alone can create false confidence when physical setup, calibration, sample, operator choice, and unchecked context are missing. | Evidence-backed inference | Medium | blind persona check; workflow improvement case; engineering guardrail | Blind persona roles warned that a versioned script is not enough to trust a result. Workflow evidence shows results depend on selected context, calibration, generated protocols, correction branches, setup diagnostics, and notebook-local choices. | Explain a run or work bundle; publish or hand off analysis; confidence/readiness review. |
| EV-031 | Live control-PC fragility is a plausible adoption risk distinct from ordinary portability. | Latent pressure | Medium | blind persona check; user context; engineering guardrail | Blind persona roles suggested rejection risk around heavy agents, fragile services, accounts, network dependencies, cloud login, or automatic driver, PATH, registry, vendor stack, and environment mutation. User context independently supports caution around working Windows control computers, but the exact rejection threshold needs interview, fixture, or installation-review evidence. | Low-risk local adoption; managed execution readiness; control-PC read-only companion validation. |
| EV-032 | A known-good reference is a natural anchor for same-setup comparison, bounded protocol transfer, rollback, and handoff. | Latent pressure | Medium | blind persona check; workflow improvement case; user context | Blind persona roles repeatedly framed the question as why last month's working run fails today, which setup state is proven to work, and how to recover after driver, package, or config changes. Workflow evidence shows folder copies, backups, run families, and local exports used as weak substitutes for known-good references. Treat cross-setup use as most plausible for same-protocol sample screening, setup comparison, or handoff, not routine same-sample migration. | Compare current state to a reference; sample-screening protocol transfer; take over an old experiment. |
| EV-033 | Diagnostic snapshots need recipient-aware sharing boundaries, not blanket redaction or blanket disclosure. | Evidence-backed inference | Medium | blind persona check; user context; engineering guardrail | Blind persona roles wanted precise, shareable support context instead of screenshots or vague failure reports. For trusted internal debugging, local paths, hostnames, instrument addresses, and LabRAD or VISA details may be essential evidence; recipient, policy, and secret-handling boundaries should determine what is redacted before public docs, external exports, or restricted support sharing. | Ask a maintainer for help; clean or share a run safely; support handoff. |
| EV-034 | Existing measurement and control frameworks already cover many run, data, metadata, instrument, scheduler, and calibration concerns. | Observation | High | external references | QCoDeS covers datasets and station/instrument snapshots; Bluesky/Event Model covers run/event documents and metadata; Labber covers instrument server, measurement editor, and log browser; BLACS covers shot compatibility checks and queues; ARTIQ covers real-time control, scheduling, GUIs, and result browsing; Qiskit Experiments and Qibocal cover specialized calibration workflows; LabRAD covers distributed modular instrument control. | Capability baseline; avoid run-history-only differentiation. |
| EV-035 | External framework coverage is strongest inside each controlled stack and weaker as a cross-stack explanation layer for inherited scripts, notebooks, physical setup context, handoff bundles, and analysis lineage. | Evidence-backed inference | Medium | external references; workflow improvement case; blind persona check; user context | Selected public docs show strong framework-local capabilities, while workflow improvement evidence and blind brainstorms repeatedly depend on copied code, local files, manual notes, setup aliases, calibration context, and analysis artifacts outside a single framework-owned model. | Explain an existing run or work bundle; compare scientific comparability; publish or hand off analysis. |
| EV-036 | Scientific comparability across screening setups, samples, or method variants is distinct from valid data storage, stable reopen, and code provenance. | Latent pressure | Medium | blind persona check; user context; workflow improvement case; external references | Blind role brainstorms repeatedly asked whether two valid-looking runs can be compared across setup, wiring, sample, method, calibration, and correction differences. Existing workflow evidence shows run families, generated protocols, corrections, and local context that affect comparison beyond raw data identity. Real-lab context narrows this from routine same-sample migration to sample screening, setup comparison, handoff, and exceptional protocol-transfer cases. | Compare screening runs or setups; navigate campaigns; hand off results. |
| EV-037 | Physical setup reality needs versioned evidence beyond instrument-driver abstraction. | Evidence-backed inference | Medium | workflow improvement case; user context; blind persona check; external references | Wiring sheets, registry files, driver initialization, setup diagnostics, instrument addresses, local aliases, and generic multi-system lab context indicate that cables, channels, sample mounts, switch paths, and manual changes affect meaning even when a driver or station snapshot exists. | Setup-reality map; known-good comparison; sample-screening setup comparison. |
| EV-038 | Calibration dependency impact should link calibration state to downstream measurements, analyses, figures, and decisions, not only to calibration routine execution. | Evidence-backed inference | Medium | workflow improvement case; external references; automation architecture notes | Qiskit Experiments and Qibocal show specialized calibration-management patterns, while workflow improvement evidence shows correction branches, readout matrices, classifiers, generated protocols, and reports whose validity depends on calibration and analysis context. | Review calibration before mutation; publish or hand off analysis; compare scientific comparability. |
| EV-039 | Analysis and publication lineage is a product gap separate from acquisition lineage. | Evidence-backed inference | High | workflow improvement case; blind persona check; external references | Workflow improvement evidence links raw data to derived arrays, notebooks, correction choices, figures, spreadsheets, decks, and reports. External baseline docs emphasize acquisition and framework-local data records more than claim-to-analysis-to-run impact review across messy lab bundles. | Publish or hand off analysis; figure impact review; take over an old experiment. |
| EV-040 | Scopecat is better positioned as a complementary explainability, comparison, and handoff layer than as a replacement measurement framework. | Evidence-backed inference | Medium | external references; workflow improvement case; user context; engineering guardrail | External frameworks already provide credible run/data/control/calibration systems. User context and workflow evidence favor low-ceremony adoption around existing scripts, Windows control PCs, copied folders, local tools, and uneven technical ownership. | Adoption ladders; validation slices; capability map. |
| EV-041 | Some experiment-critical physical and sample facts cannot be verified from software alone. | Evidence-backed inference | Medium | user context; workflow improvement case; engineering guardrail | Actual physical wiring, switch paths, mounted sample identity, chip topology, line attenuation, and qubit/gate/channel/instrument correspondences may be declared manually, inferred from files, or checked indirectly, but software records alone cannot prove them. | Setup-reality map; scientific comparability; known-good comparison; handoff. |
| EV-042 | Manual setup and topology records have low maintenance value unless they power concrete user-facing tasks. | Latent pressure | Medium | user context; workflow improvement case | The same physical context can be valuable when used to find a qubit's instrument or channel, calculate line attenuation, visualize parameters on a chip layout, compare setup variants, or prepare handoff; otherwise it becomes stale metadata work. | Setup-reality map; useful context schema; handoff; diagnostics. |
| EV-043 | Experiment parameter schemas and physical-configuration schemas need local evolution rather than a fixed universal model. | Evidence-backed inference | Medium | user context; workflow improvement case; automation architecture notes | Parameter files, registry files, wiring sheets, generated summaries, sample variants, and method changes show schema pressure that is hard to predefine globally, but often stable enough inside a bounded campaign, sample, method, or setup period to be versioned and reused. | Parameter memory; setup-reality map; scientific comparability; validation slices. |
| EV-044 | Analysis handoff from an experiment-control computer to a user's analysis computer is a high-priority adoption pressure distinct from cross-machine scientific comparison. | Evidence-backed inference | Medium | user context; workflow improvement case | User refinement emphasized finding high-value data by experiment name, measurement-object label, quick plot, and star/favorite mark, then moving selected data and context to a personal analysis computer for deeper analysis, figure making, and reporting. Workflow evidence already shows derived arrays, figures, notebooks, spreadsheets, decks, and source-identity loss. | Publish or hand off analysis; starred runs to analysis handoff package; figure impact review. |
| EV-045 | Predecessor Fricon data-shape work provides validation coverage for handoff and durable-record journeys without defining Scopecat's storage, reader API, export format, or UI. | Observation | High | predecessor project docs; research extraction | Prior Fricon documents identify regular one-, two-, and N-dimensional sweeps, trace-valued records with explicit or compact coordinates, multiple traces per outer record, first-class complex values, IQ averages/channels/single-shot arrays/labels, and generic irregular or ragged step records for minimizer-like output. | Analysis handoff validation; durable measurement record; reader and preview validation. |
| EV-046 | Long-running measurement decision support is a distinct pressure from live plotting or post-run analysis handoff. | Latent pressure | Medium | user refinement; blind framework role-play | User refinement and blind role-play across QCoDeS, Labber-like, Bluesky/Event Model, and LabRAD/Data Vault lenses converged that existing systems often cover live data and plots, while the unresolved pain is deciding whether a long run is still worth continuing before the full run ends. | Measurement-time decision support; durable measurement record; calibration review; analysis lineage. |
| EV-047 | Measurement-time feedback must be method-aware, replayable, explicitly recorded, and non-intrusive to differentiate from existing measurement frameworks. | Latent pressure | Medium | user refinement; blind framework role-play; external-framework baseline | Blind framework role-play narrowed the useful capability to passive advisory feedback that understands method intent, completed sweep or stream slices, fit/quality/anomaly evidence, thresholds, uncertainty, and replayable provenance. User refinement further narrows the integration boundary: Scopecat should require experiment code to record data, sweep semantics, lifecycle events, and decision-relevant context into Scopecat rather than relying on passive scraping or framework-specific auto-adapters. It should not replace QCoDeS, Labber, Bluesky, LabRAD/Data Vault, local scripts, dashboards, callbacks, or hardware control. | Measurement-time decision support; known-good comparison; calibration proposal review; control-PC read-only companion validation. |

## Pain Ranking Rubric

Pain order is now direction-bias corrected for selecting the next journey. It
is based on:

- workflow improvement case signal density;
- Scopecat leverage without claiming authoritative ownership of opaque files;
- ability to validate the pain without device control, write-back, or broad
  managed execution;
- pain visibility, so directly observed artifact pain does not crowd out latent
  workflow pressure created by the old system's limits;
- fit with a thin vertical journey that can still preserve future platform
  composition.

IDs remain stable. Table order may change as new evidence arrives.

## Pain, JTBD, Capability, And Baseline Separation

The `PN` prefix was originally used for all pain-shaped pressure. That is still
useful for stable cross-reference, but Journey selection should not treat every `PN` row as
the same kind of thing. Some rows are natural decompositions of top-level pains;
some are adoption guardrails; some are jobs-to-be-done candidates; some are
capability gaps; and some are expected measurement-framework baseline behavior.

Use this separation when selecting journeys:

| Statement kind | Meaning | Journey-selection handling |
| --- | --- | --- |
| Foundational pain | A user-facing inability, risk, or costly workaround that naturally decomposes a `TP` narrative. | Can become acceptance pressure for a journey after evidence and boundary checks. |
| Adoption blocker or guardrail | A reason users or maintainers would reject the tool even if the main journey looks useful. | Constrain the journey; do not automatically turn into feature scope. |
| JTBD candidate | A situational job that should be phrased as "when..., help me..., so I can..." in a journey. | Convert into current-state and future-state journey text before implementation planning. |
| Capability gap | A desired system capability that existing measurement/control frameworks cover weakly, locally, or only in controlled stacks. | Use for differentiation only when tied back to a top-level pain, evidence, and a fixture. |
| Existing-framework baseline or validation case | Behavior users may reasonably expect from mature measurement/data systems, or a technical case needed to validate a model. | Treat as substrate, fixture, acceptance detail, or non-differentiating capability; do not present as the product's main pain. |

Current classification is approximate because a row can have secondary roles.
It is still useful for avoiding priority inflation.

| Current rows | Primary kind | Natural top-level-pain link | Journey-selection implication |
| --- | --- | --- | --- |
| PN-001, PN-002, PN-005, PN-006 | Foundational pains | Natural decompositions of TP-002, TP-004, TP-005, and TP-006; PN-005 and PN-006 also support the software/code-facing parts of TP-009. | Keep as the primary JC-001 acceptance cluster. |
| PN-003, PN-017, PN-018 | JTBD and capability candidates | Natural from TP-001 and TP-003, but too capability-shaped to accept directly. | Convert into proposal-review, plan-preview, or dry-run package journeys before implementation scope. |
| PN-004, PN-010, PN-011, PN-012, PN-019, PN-029, PN-030 | Lineage, handoff, and campaign validation cases | Natural from TP-003, TP-005, TP-006, TP-008, and TP-009 when the fixture contains generated protocols, correction branches, run families, figures, code-shaped method history, or manual interventions. | Pull into journey selection only when the selected fixture needs them; otherwise keep as follow-on validation. |
| PN-020, PN-021, PN-022, PN-023, PN-024, PN-025 | Adoption-risk hypotheses and guardrails | Natural decomposition of TP-007, and guardrails for TP-009 when shared code/config records could drift from real machines or lab practice. | Constrain early journeys around truth drift, false confidence, control-PC safety, share-boundary handling, known-good references, and recovery evidence; validate exact rejection thresholds before treating them as proven user blockers. |
| PN-026, PN-027, PN-028, PN-031, PN-032 | Capability-gap pains | Natural decomposition of TP-008 and the method-comparison parts of TP-009. | Use to test differentiation around comparability, full-stack diff, setup reality, metadata ROI, and local schema evolution. |
| PN-033, PN-034, PN-035, PN-036, PN-037 | Measurement-time decision-support pains | Natural decomposition of TP-010, with PN-022 and PN-021 as adoption and confidence guardrails. | Validate as an explicit-recording watchdog or decision-support fixture before accepting live analysis, recommendations, alerting, or any connection to calibration automation. |
| PN-007, PN-015, PN-016 | Adoption affordances and portability guardrails | Support TP-002, TP-005, TP-006, TP-007, and TP-009, but are not the center of a pain narrative. | Keep as acceptance constraints around portability, low ceremony, and quick handoff affordances. |
| PN-008, PN-009, PN-013, PN-014 | Existing-framework baseline, model question, or future technical pressure | Can support TP-001, TP-002, and TP-004, but are not strong top-level-pain decompositions by themselves. | Use as substrate or validation detail; avoid positioning lifecycle state, source-of-record clarity, setup manifests, or parameter-history model questions as primary differentiation. |

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

## Pain And Pressure Inventory

Visibility values are intentionally coarse: `direct`, `inferred`,
`latent`, `interview`, and `future/ADR`. A row may use more than one when the
pain is partly visible but its highest-value future workflow is not.

| ID | Selection signal | Visibility | Validation route | Pain point | Evidence | Journey-selection notes |
| --- | --- | --- | --- | --- | --- | --- |
| PN-002 | Strong journey candidate; workflow improvement case led. | direct | Case fixture with selected context candidates and conflicts. | I do not know which parameter, registry, wiring, generated settings file, or external record was selected for this run, or whether that context is stale or ambiguous. | EV-003, EV-004, EV-015 | Surface selected context candidates, ambiguity, freshness, and conflicts. Do not infer authoritative truth from arbitrary files. |
| PN-006 | Strong journey candidate; workflow improvement case led. | direct | Case fixture linking output to notebooks, scripts, packages, backups, and generated artifacts. | I cannot tell which notebook, script copy, package snapshot, or backup branch produced this output. | EV-006, EV-008 | Treat notebooks, copied code, backups, generated bytecode, and package snapshots as provenance evidence before managed execution. |
| PN-005 | Strong journey candidate; workflow improvement case led. | direct; inferred | Static readiness fixture or spike that records environment, dependency, entrypoint, and fail-before-write checks. | I cannot tell whether this code or measurement stack can run safely on the current control computer after changes, in an inherited bundle, or on a planned screening setup. | EV-006, EV-007, EV-021, EV-023, EV-026, EV-027 | Environment manifest, dependency summary, and fail-before-write readiness are useful before managed runner scope. |
| PN-001 | Strong journey substrate; no longer the sole first-center by default. | direct | Case fixture that uses run or dataset identity as the anchor for context, code, and artifact explanation. | I can reopen raw data but cannot explain the result without hunting for companion artifacts and context. | EV-001, EV-002, EV-003, EV-010, EV-016 | Use run or dataset identity as the anchor for context, code, and artifact explanation rather than treating stable reopen alone as the journey. |
| PN-012 | Near validation case; workflow improvement case led. | direct; inferred | Generated-protocol fixture with sequence, source, seed, backend map, and basis metadata. | I cannot reproduce a randomized or generated-protocol experiment unless the generated sequence, seed/source, backend map, and basis metadata are preserved. | EV-019 | Treat generated circuits/sequences as protocol or design artifacts, not generic companion artifacts. Pull into the first journey if the chosen fixture uses generated protocols. |
| PN-010 | Near validation case; workflow improvement case led. | direct | Lineage fixture with readout, SPAM, classifier, manual override, and corrected/uncorrected branch evidence. | I cannot tell which readout correction, mitigation matrix, manual override, classifier, or corrected/uncorrected branch produced this result. | EV-017 | Keep close to the first lineage fixture when readout, SPAM, classifier, or correction evidence is central. |
| PN-011 | Near validation case; workflow improvement case led. | direct | Run-family fixture with round recipe, indexing convention, feedback records, and selected ranges. | I cannot reopen a multi-round or feedback experiment from one dataset ID; I need the run-family recipe and indexing convention. | EV-018 | Keep close to the first lineage fixture when round families, feedback records, or indexed recipes are present. |
| PN-004 | Strong follow-on journey candidate. | direct; inferred | Handoff fixture linking selected or starred pre-analysis data and minimal context back to source runs, required sidecars, source paths, and explicit missing-context warnings. | I cannot find and take high-value data off the experiment computer for deeper analysis, figure making, or publication without losing links back to source runs, companion artifacts, corrections, and decisions. | EV-002, EV-008, EV-009, EV-013, EV-017, EV-022, EV-028, EV-044, EV-045 | Good follow-on if the first accepted journey establishes bundle identity across context, code, and generated artifacts. Prioritize internal full-fidelity analysis handoff before public/reference export; see [`../journeys/jc-002/README.md`](../journeys/jc-002/README.md) for current candidate details, snapshot definition, validation coverage, live-preview boundary, and deferred design questions. Avoid a full ELN, report generator, generic export-format-first design, permission system, or complete work-bundle export/import. |
| PN-003 | High value; mutation-gated. | direct; future/ADR | Proposal-only calibration journey or spike with before/after snapshots, evidence, review, diff, and rollback target. | I cannot safely review calibration changes before they mutate durable settings. | EV-004, EV-005 | First slice should be proposal/evidence only. Write-back requires ADRs, review boundaries, and rollback semantics. |
| PN-017 | Latent journey gap; scan-preview shaped. | latent; inferred | Scan-plan spike or fixture using existing scan loops and generated protocol artifacts without device apply. | I cannot preview, diff, freeze, or review an experiment plan before it touches hardware. | EV-010, EV-016, EV-019, EV-024 | This is not as directly visible as artifact recovery, but it is central to avoiding a run-history-only direction. Keep it as a journey-selection question unless the first fixture requires pre-run control. |
| PN-018 | Latent journey gap; managed-execution shaped. | latent; inferred | Dry-run, template-reuse, or execution-package spike with code, context, generated artifacts, environment, expected outputs, and validation result. | I cannot package a planned run or reusable method so another person or machine can validate what will run before execution. | EV-004, EV-006, EV-007, EV-015, EV-019, EV-024, EV-026, EV-027 | Useful to preserve managed-runner pressure without accepting scheduler, queue, remote execution, or device-control scope. Cross-control-computer reuse should treat code, settings, and setup assumptions as template or reference evidence, not a complete work-bundle import into active truth. |
| PN-020 | Adoption-risk hypothesis; blind-persona led. | latent; inferred | Prototype or interview check that shows Scopecat records as evidence with freshness, source, and ambiguity labels instead of authoritative config. | I cannot trust a workflow tool that becomes another drifting source of truth beside scripts, the control PC, existing config files, and lab notes. | EV-004, EV-015, EV-029 | Constrain early records to observed, declared, selected, proposed, applied, missing, stale, and unchecked states. Do not accept hidden config ownership or silent write-back. |
| PN-021 | Cross-cutting confidence-risk hypothesis; blind-persona led. | latent; inferred | Confidence/readiness fixture that reports missing context, stale calibration, manual overrides, unchecked setup, and unverified code without collapsing them into one score. | I cannot tell whether a well-versioned record is actually safe to trust, or whether it only looks complete because software provenance was captured. | EV-002, EV-003, EV-005, EV-011, EV-017, EV-030 | Prefer explainable confidence signals over a numeric confidence score until the first journey proves which gaps users act on. |
| PN-024 | Comparator hypothesis; blind-persona led. | latent; inferred | Known-good reference fixture comparing a current run, machine, inherited bundle, or screening setup against a selected working reference. | I cannot tell which run, setup state, environment, or method version is the known-good reference for same-setup comparison, bounded protocol transfer, handoff, or recovery. | EV-006, EV-007, EV-015, EV-020, EV-032 | Use known-good references as comparison anchors, not as automatic authority over config, rollback, deployment, or import. Do not assume routine same-sample migration or high demand for cross-machine data comparison across equipment groups; analysis handoff and code/method template reuse are separate cases. |
| PN-026 | Capability-gap journey candidate; external-baseline led. | latent; inferred | Two-run or two-setup comparability fixture that contrasts intent, selected context, setup, calibration, generated protocol, correction, and analysis lineage. | I cannot tell whether two valid-looking screening runs, setup variants, samples, or method variants are scientifically comparable, or which differences invalidate the comparison. | EV-017, EV-018, EV-025, EV-030, EV-034, EV-035, EV-036 | Treat this as scientific comparability, not generic data normalization or routine same-sample cross-equipment movement. Surface evidence and gaps; do not infer authoritative truth from opaque files. |
| PN-027 | Capability-gap journey candidate; known-good diff led. | latent; inferred | Full-stack diff fixture from a selected known-good reference to a current bundle, machine, or screening setup. | I cannot see what changed since the last trusted run across code, environment, selected context, calibration, physical setup, manual interventions, generated artifacts, and analysis choices. | EV-006, EV-007, EV-015, EV-019, EV-032, EV-035, EV-037, EV-041 | Extends PN-024 from finding a reference into explaining actionable differences. Keep it diagnostic; no rollback, deployment, or device mutation. |
| PN-028 | Capability-gap validation case; setup-reality led. | direct; inferred | Setup map fixture using wiring files, registry/config files, driver initialization evidence, setup diagnostics, aliases, and manual annotations. | I cannot recover the physical setup reality behind instrument aliases, channel names, cables, switch paths, sample mounts, chip topology, and manual changes over time. | EV-011, EV-026, EV-028, EV-035, EV-037, EV-041 | Start with versioned evidence, source, freshness, verification status, and ambiguity labels. Do not claim live device state, software-proven physical truth, or authoritative lab inventory ownership. |
| PN-029 | Capability-gap follow-on; analysis-impact led. | direct; inferred | Figure or claim impact fixture linking raw data, processing notebooks, fit or result evidence, exclusions, calibrations, setup context, and rerun history. | I cannot tell which figures, fits, reports, or conclusions need rechecking after a calibration, setup, code, or analysis change. | EV-009, EV-017, EV-022, EV-038, EV-039 | Keep this as analysis lineage and impact review. Treat fit/result record shape as a validation question for an accepted analysis-impact or handoff journey, not a prescribed early schema. Avoid turning an early journey into a full publication workflow, ELN, or report generator. |
| PN-030 | Capability-gap validation case; lab-memory led. | inferred; latent | Failure and manual-intervention fixture that records intervention, reason, affected state, outcome, and whether the evidence is reusable. | I cannot learn from failed, partial, or manually rescued runs because interventions and failure modes are not structured as reusable evidence. | EV-012, EV-020, EV-028, EV-035, EV-037, EV-039 | Preserve manual events and failure evidence as context. Do not make this a lab-wide ticketing or incident-management product. |
| PN-031 | Capability-gap guardrail; metadata-ROI led. | latent; inferred | Useful-context fixture that turns a small declared setup or topology schema into lookup, attenuation calculation, layout visualization, comparability, or handoff output. | I cannot justify manually maintaining physical setup, chip topology, or alias metadata unless the system uses it for concrete experiment work. | EV-037, EV-041, EV-042 | Validate value-producing use before asking users to maintain detailed setup or topology records. Avoid high-ceremony metadata capture for its own sake. |
| PN-032 | Capability-gap guardrail; schema-evolution led. | latent; inferred | Schema-evolution fixture using one campaign or setup period with versioned local parameters, aliases, physical context, and changed fields. | I cannot fit every experiment into a fixed parameter or setup schema, but I still need records that evolve coherently as parameters and physical configuration change over time. | EV-004, EV-015, EV-024, EV-037, EV-041, EV-043 | Support local schema versions, validity periods, aliases, and approximate continuity. Do not require a global ontology or one schema that fits all experiments in early journey work. |
| PN-033 | Latent journey gap; user-refinement led. | latent; inferred | Long-running sweep fixture where experiment code explicitly records partial data, sweep semantics, completed analysis slices, and expected fit or quality outputs into Scopecat. | I cannot get fit, quality, anomaly, or derived-result feedback when the relevant sweep slice is complete; I have to wait for the whole long-running measurement before knowing whether the data is useful. | EV-010, EV-016, EV-045, EV-046, EV-047 | Treat as measurement-time decision support, not generic live plotting. Validate explicit recording, completed-slice detection, and user-visible value before accepting any live-analysis surface. |
| PN-034 | Decision-provenance validation case. | latent; inferred | Watchdog fixture that records stop, continue, retune, repeat, or zoom recommendations with the data available at decision time. | I cannot preserve the evidence behind measurement-time stop, continue, retune, repeat, or zoom recommendations. | EV-017, EV-029, EV-038, EV-039, EV-046, EV-047 | Recommendations should be append-only evidence linked to data slices, metrics, thresholds, uncertainty, plots, and operator action. They are not hardware commands or proof of scientific truth. |
| PN-035 | Confidence and replay guardrail. | latent; inferred | Replay fixture that runs the same live-analysis configuration over recorded input and reproduces displayed intermediate results. | I cannot tell whether a live fit or quality metric is a preview estimate, a validated result, or only an operator decision aid, and I cannot replay the same intermediate result later. | EV-021, EV-030, EV-034, EV-046, EV-047 | Distinguish preview, validated result, and decision aid. Preserve analysis configuration, code or model version, preprocessing, bounds, excluded points, convergence status, residuals, and fit uncertainty where relevant. |
| PN-036 | Method-aware watchdog capability gap. | latent; inferred | Method-specific rules fixture using a small set of expectations such as peak shift, saturation, missing feature, SNR plateau, ROI coverage, or expected envelope comparison. | I cannot express lightweight method-specific expectations for a running measurement without building a full workflow engine, replacing the measurement framework, or hiding logic in one-off notebooks. | EV-019, EV-021, EV-024, EV-034, EV-046, EV-047 | Keep method logic pluggable and inspectable. Avoid opaque AI advice, generic workflow DAG scope, and framework replacement. |
| PN-037 | Live-adoption guardrail; control-path safety led. | latent; inferred; future/ADR | Explicit-recording fixture where user experiment code writes measurement data, sweep semantics, lifecycle events, and decision-relevant context to Scopecat, with graceful failure and no acquisition dependency. | I cannot adopt measurement-time decision support if it interferes with existing acquisition, control PCs, timing, hardware-control systems, or local data ownership. | EV-026, EV-027, EV-031, EV-034, EV-040, EV-047 | First slice should be passive with respect to hardware control and disposable: record, analyze, annotate, alert, and recommend from information deliberately sent to Scopecat. Do not touch device state, scan plans, parameter write-back, vendor software, drivers, acquisition acknowledgement paths, mid-write files, live control scripts, or instrument polling. Passive does not mean disconnected: a useful slice still needs enough live observation surface, such as active run state, progress, plots, fit overlays, quality flags, anomaly markers, and recommendation evidence, so users are not forced to stitch together one GUI for measurement context and another for decisions. |
| PN-022 | Adoption-risk constraint; control-PC safety led. | inferred; future/ADR | Low-risk read-only companion prototype, interview, or installation review on a representative Windows control-PC workflow. | I cannot adopt a tool that adds fragile services, accounts, network dependencies, cloud login, or automatic driver/environment mutation to a working control computer. | EV-026, EV-027, EV-031 | Make low-risk operation an acceptance constraint for early slices, but validate the exact rejection threshold. Do not accept background agents, mandatory network services, package management, driver mutation, or registry/PATH changes from early journey work. |
| PN-025 | Supporting rollback concern; maintainer led. | inferred; future/ADR | Change-impact or rollback-evidence fixture that records what changed and what known-good reference to return to, without performing rollback. | I cannot recover a working experiment state quickly after a dependency, driver, vendor tool, or config change breaks the setup. | EV-007, EV-026, EV-027, EV-031, EV-032 | Preserve rollback pressure as diagnostic and reference evidence first. Automatic restore, environment management, and driver rollback are later decisions. Treat cross-setup recovery as a screening/setup-comparison case unless fixture evidence says otherwise. |
| PN-023 | Support and share-boundary constraint. | inferred | Boundary-aware diagnostic-package fixture for asking a trusted internal maintainer to debug a failed or questionable run, with sanitization when the package crosses a public, external, restricted, or policy-sensitive boundary. | I cannot ask a maintainer for help cleanly because the useful diagnostic context is either missing and vague, or bundled with local details whose sensitivity depends on who receives it. | EV-013, EV-022, EV-027, EV-033 | Preserve recipient-appropriate diagnostic detail; redact secrets and apply policy before public, external, or restricted sharing. Do not make this a general bug-reporting product in early journey work. |
| PN-019 | Latent journey gap; campaign shaped. | latent; inferred | Interview prompt plus campaign fixture with run families, corrections, selected ranges, and summaries. | I cannot ask higher-level questions across a campaign because records are file-shaped rather than concept-shaped. | EV-017, EV-018, EV-022, EV-025, EV-028 | Keep as a validation case unless the selected journey source bundle is already a campaign. Do not broaden first scope into a full scientific workflow model. |
| PN-016 | Adoption constraint. | interview; inferred | Low-ceremony prototype or interview check against ordinary Python and notebook-heavy workflows. | I need to start recording from ordinary Python without adopting a managed framework, excessive metadata ceremony, or unsafe writes. | EV-007, EV-021, EV-023, EV-027 | Preserve low ceremony as an acceptance criterion, but do not let predecessor project interview wording force run-history-first scope. |
| PN-015 | Adoption constraint. | interview; inferred | Usability check in any run or bundle explanation journey. | I need stable ID copy or reader snippets as the fastest path into existing analysis code. | EV-003, EV-023 | Useful acceptance criterion for any run or bundle explanation journey. |
| PN-007 | Portability guardrail. | direct; inferred | Sanitized handoff or reuse fixture that exposes local path, machine, and lab-specific coupling without public leakage. | I cannot cleanly reuse, share, or export a run when local paths and machine-specific details are embedded in the evidence. | EV-008, EV-013, EV-022, EV-026 | Should constrain handoff/export design; public export may add redaction requirements. |
| PN-014 | Future pressure; parameter-memory shaped. | inferred; latent | Parameter snapshot or proposal spike that separates file-copy history, notebook mutation, and commit stream concepts. | I cannot tell whether parameter history is file-copy history, notebook mutation history, or a local database commit stream. | EV-004, EV-015 | Evidence for parameter proposals and snapshot concepts; local config-history experiments should not define the model alone. |
| PN-008 | Future pressure; partly ADR-gated. | direct; future/ADR | Setup manifest or lease question after safety boundaries are explicit. | I cannot preserve useful setup or hardware bring-up context without pretending Scopecat controls or understands the device state. | EV-004, EV-011 | Diagnostics and manifests may be useful; device apply/control is not early journey work scope. |
| PN-009 | Supporting lifecycle concern. | inferred; interview | Fixture with incomplete, interrupted, failed, invalidated, or corrected run state if the selected journey needs it. | I cannot reliably understand incomplete, interrupted, failed, invalidated, or corrected runs. | EV-012, EV-020 | Include readable lifecycle and outcome state where a selected fixture needs it, but defer resumability. |
| PN-013 | Supporting source-of-record concern. | inferred | Source-of-record fixture contrasting primary record, overwritten export, and adjacent single-shot artifact. | I cannot tell whether the authoritative data is the primary record, an overwritten export, or an adjacent single-shot artifact. | EV-020 | Source-of-record concerns should become evidence, not Data Vault bypass behavior. |

## Top-Level Pain Narratives

Top-level pain narratives are user-language problem statements that are too
broad to become first slice acceptance criteria directly. They are useful
because they keep system-level pressure visible while the foundational `PN`
items stay small, testable, and boundary-aware.

This is pain decomposition: a narrative can seed a journey, but it is not the
journey itself. A journey still needs actors, sequence, entry and exit
conditions, stakes, and acceptance checks.

Treat top-level pains as composition pressure, not single-ladder
implementation requirements. A TP may need several adoption ladders to fully
resolve in the complete system, while any promoted adoption slice should
validate one narrow, independently valuable path and must not require users to
adopt the whole platform at once.

| ID | Top-level pain narrative | Why it matters | Decomposed foundational pains | Candidate validation route | Boundary |
| --- | --- | --- | --- | --- | --- |
| TP-001 | I cannot design a reliable scheduled background qubit calibration system. | Stress-test narrative for avoiding run-history-only scope: reliable background calibration requires plan preview, code and context binding, runtime readiness, execution records, result review, proposal semantics, and lineage into later experiments. | PN-017, PN-018, PN-003, PN-005, PN-010, PN-011, PN-014, PN-008, PN-009 | Interview prompt plus a staged path: plan-preview fixture, dry-run package spike, proposal-only calibration review, then ADRs for autonomous mutation and device apply. | Do not accept autonomous scheduling, hardware control, or durable settings mutation from early journey work. Use this only to test cross-capability composition. |
| TP-002 | I cannot tell which code and context are safe to use on this control computer or a screening setup, so I copy a working bundle before using it. | Exposes that code identity, execution environment, selected configuration, setup context, portability, and technical-owner boundaries are separate problems. Folder copy is a symptom, not the desired workflow, and cross-setup pressure should not imply routine same-sample migration. | PN-006, PN-005, PN-002, PN-018, PN-007, PN-014, PN-008, PN-015, PN-016 | Same-setup readiness or sample-screening protocol-transfer fixture or interview: compare code, entrypoint, dependencies, selected context, generated artifacts, and setup manifests without touching hardware. | Do not turn this into a full deployment, package-management, or remote-execution product before the minimal readiness record is validated. |
| TP-003 | A new sample, chip design, or experiment plan changed, so I copy a code tree before starting for safety. | Captures variant and isolation pressure: users need to fork methods safely, bind sample/design context, detect stale assumptions, and preserve lineage without relying on directory copies. | PN-006, PN-002, PN-017, PN-012, PN-010, PN-011, PN-014, PN-007 | New-sample method-variant fixture: compare old and new assumptions, generated protocols, calibration/correction applicability, parameter snapshots, and run-family lineage. | Do not require a full design database or method authoring environment. Start with context binding, diff, and provenance. |
| TP-004 | There are too many experiment versions on this computer, so I have given up organizing them. | Good evidence of cognitive and operational overload, but dangerous if treated as a generic file-management request. The useful Scopecat pressure is concept-shaped recovery across runs, code, context, artifacts, and decisions. | PN-001, PN-006, PN-002, PN-004, PN-011, PN-019, PN-007, PN-013 | Case fixture that classifies active, obsolete, backup, failed, published, and source-of-record artifacts inside one work bundle or campaign. | Avoid building a general file organizer. Validate only the experiment concepts needed to recover provenance and intent. |
| TP-005 | I cannot hand an experiment to another person or future me with confidence. | Pulls together analysis handoff, selected context, portability, execution readiness, generated artifacts, and decision trail without prematurely specifying a collaboration product. The strongest near-term handoff pressure is often moving high-value data and provenance from a control computer to a user's analysis computer for deeper analysis and publication work. | PN-004, PN-002, PN-006, PN-005, PN-012, PN-018, PN-007, PN-015 | Handoff fixture: package analysis-ready data or an existing run with source runs, code, context, generated artifacts, validation status, and unresolved ambiguity. | Do not accept a full ELN, report generator, collaboration workflow, scheduler, remote execution, device-control scope, or complete work-bundle export/import before bundle identity and source links are validated. |
| TP-006 | I cannot take over an old experiment with confidence. | Captures personnel turnover and midstream handoff pressure: successors need to recover intent, active versus obsolete artifacts, code provenance, selected context, readiness, and lineage without relying on the previous user's memory. | PN-001, PN-002, PN-004, PN-005, PN-006, PN-007, PN-011, PN-012, PN-015, PN-018, PN-019 | Takeover fixture or interview: start from an inherited folder, notebook, report, or run family and identify source runs, selected context, active code, generated artifacts, handoff gaps, and unresolved ambiguity. | Do not turn this into onboarding, training, a full ELN, or lab knowledge management. Validate the minimum source identity, context bundle, provenance, readiness, and handoff package needed to continue work. |
| TP-007 | I cannot tell whether a reliability tool will reduce experiment risk or become another fragile, misleading system to maintain. | Blind persona checks suggested adoption-risk hypotheses that are easy to miss when reading existing docs: a new truth store can drift, partial provenance can create false confidence, control-PC changes can break scarce measurement windows, and maintainers need precise diagnostics whose sharing boundary is explicit. | PN-020, PN-021, PN-022, PN-023, PN-024, PN-025, PN-005, PN-007, PN-016, PN-018 | Read-only companion adoption fixture: compare a known-good reference with the current bundle or machine, show confidence gaps, produce a recipient-appropriate diagnostic package, and avoid any live mutation. | Do not accept authoritative config ownership, automatic environment management, background control-PC services, driver mutation, cloud dependency, rollback automation, or device control from this narrative. |
| TP-008 | Existing measurement frameworks can run and store measurements, but I still cannot tell whether a result should be trusted, compared, screened, or handed off across a real lab. | External framework baselines show strong local answers for acquisition, metadata, control, scheduling, and calibration. The remaining pressure is a cross-stack layer for scientific comparability during screening or exceptional transfer, full-stack diffs, setup reality, manual interventions, calibration impact, analysis lineage, useful declared physical context, and evolvable local schemas. | PN-026, PN-027, PN-028, PN-029, PN-030, PN-031, PN-032, PN-001, PN-002, PN-004, PN-005, PN-021, PN-024 | Capability-gap fixture or interview: start with two valid-looking screening runs, a known-good reference, a small declared setup/topology schema, or a figure/report and ask which hidden differences matter scientifically and which manual records earn maintenance effort. | Do not position Scopecat as a replacement for QCoDeS, Bluesky, Labber, ARTIQ, LabRAD, or calibration-specific tools. Do not require software-proof of physical truth, routine same-sample cross-equipment migration, or a universal schema. Validate complementary explanation and comparison first. |
| TP-009 | I cannot turn lab experiment code and runnable configuration into maintained shared assets; LabRAD setup, Python environments, waveform tools, analysis scripts, calibration protocols, gate definitions, and custom waveforms keep fragmenting into copied local folders. | Combines the lab-management pressure behind software readiness and code-shaped method knowledge. The useful asset may be a runnable environment, a shared utility, a waveform or gate layer, an analysis routine, a calibration protocol, or evidence about which copied version is known-good and why. Cross-control-computer reuse is more plausibly template/reference reuse than complete bundle import. | PN-006, PN-005, PN-004, PN-010, PN-011, PN-012, PN-018, PN-019, PN-020, PN-021, PN-023, PN-024, PN-027, PN-030, PN-016 | Shared-code/config fixture or interview: compare a known-good machine or code source with copied local variants, then recover source identity, runnable dependencies, reusable layers, validation evidence, drift, diagnostic boundaries, and which settings can serve as seed values. | Record, compare, validate, and diagnose shared code/config assets first. Do not turn this into Git hosting, package registry, deployment management, automatic environment sync, a general wiki, ELN, code review platform, authoritative config owner, or full work-bundle import. |
| TP-010 | I cannot tell during a long-running measurement whether the run is still worth continuing, because fit, quality, anomaly, and intent-specific feedback arrives too late or is not decision-grade. | User refinement and blind framework role-play suggest a narrow but distinct pressure: existing systems often provide acquisition, live plotting, callbacks, dashboards, and metadata, but users still need passive, method-aware, replayable decision support that says whether to continue, stop, retune, repeat, zoom, or adjust the next run, with evidence. This overlaps calibration automation through fit, quality, proposal, and decision records, but should start as measurement-time advisory support rather than parameter mutation or hardware control. TP-010 is a composition pressure: later full-system value may combine measurement recording, scan semantics, parameter context, code identity, analysis lineage, and live observation, but any promoted slice should validate an explicit recording path rather than require every ladder at once. | PN-033, PN-034, PN-035, PN-036, PN-037, PN-009, PN-021, PN-022, PN-024, PN-029 | Long-run watchdog fixture or interview: user experiment code explicitly records data, sweep semantics, lifecycle events, and decision-relevant context into Scopecat; Scopecat detects completed analysis slices, produces fit, quality, anomaly, and method-intent feedback, records decision packets, and replays the same recommendations from recorded inputs. | Do not turn this into a replacement for the lab's existing measurement/control GUI, control framework, workflow engine, autonomous calibration loop, hardware controller, parameter write-back system, cloud service, opaque AI advisor, passive scraping layer, or framework-specific adapter matrix. A promoted slice should be explicitly recorded, passive with respect to hardware control, inspectable, replayable, and safe to disable without changing the experiment. |

## Journey Candidates

Rows are ranked by direction-bias corrected evidence fit, not by final product
priority. Top-level pain narratives can seed journey selection, but the selected
journey should still define a narrow future-state slice in terms of
foundational pains, fixtures, and boundaries.

Later rows may still close important composition gaps. Promote them earlier if
a selected journey depends on their substrate or runtime boundary.

| ID | Drafting signal | Candidate journey | Why it fits now | Main boundary |
| --- | --- | --- | --- | --- |
| JC-001 | 1 | Explain an existing run or work bundle with selected context, code, and artifacts | Directly addresses PN-002, PN-006, PN-005, and PN-001; uses stable run/dataset identity as an anchor while making selected configuration, code provenance, dependency readiness, companion artifacts, and ambiguity visible. | Do not require managed execution, device control, old-history import, write-back, or claims that Scopecat owns parameters, setup, notebook state, code execution, or arbitrary legacy-file truth. |
| JC-002 | 2 | Starred runs to analysis handoff package | User refinement raises internal analysis handoff above cross-machine scientific comparison as a nearer adoption pressure. This tests PN-004 with EV-044 and EV-045: users need to find high-value runs, inspect simple historical previews, mark or multi-select them, and move an immutable pre-analysis data-plus-context snapshot from an experiment-control computer to a personal analysis computer without losing source identity. | Drafting details live in [`../journeys/jc-002/README.md`](../journeys/jc-002/README.md). Do not accept public/reference packaging, full publication workflow, generated-report scope, generic export-format-first design, full work-bundle export/import, live-monitor semantics, managed analysis-script execution, permission systems, or reader/API/storage/UI/schema details. |
| JC-009 | 3 | Compare a known-good reference with a current bundle, machine, or screening setup | Blind persona checks suggested plausible adoption risks around "last month worked, today fails" and "can this protocol be reused on another screening setup without wasting the slot." This tests PN-005, PN-020, PN-021, PN-022, PN-024, and PN-025 while keeping the first slice diagnostic and avoiding a claim of validated cross-setup demand. | Comparison, confidence gaps, and diagnostic evidence only; no rollback automation, package installation, driver mutation, cloud service, authoritative config write-back, device control, or assumption that one sample routinely moves across equipment groups. |
| JC-010 | 4 | Compare scientific comparability between screening runs, setups, samples, or method variants | External framework baselines and blind capability-gap brainstorms point to a gap beyond run storage: users need to know whether valid-looking screening or method-variant results can be compared across setup, sample, calibration, generated protocol, correction, and analysis differences. | Evidence and gap review only; no automatic scientific equivalence judgment, generic data normalization, software-proof of physical truth, authoritative setup model, universal schema, full campaign workflow, or routine same-sample cross-equipment migration assumption. |
| JC-004 | 5 | Clean notebook and copied-code provenance | The workflow improvement case has dense notebook, backup, copied module, checkpoint, and generated-bytecode evidence; this validates code/notebook evidence capture before managed execution. | Link notebooks, scripts, packages, and generated artifacts as evidence; do not accept automatic notebook-state capture or package-registry scope. |
| JC-006 | 6 | Preserve generated protocol, correction, and run-family lineage | The workflow improvement case strongly exercises PN-010, PN-011, and PN-012 through generated circuits, per-round records, tomography/QPT, readout correction, classifier, and feedback artifacts. | Keep as a close validation path for JC-001/JC-002 unless the selected journey selection fixture requires it; do not broaden first slice into a full scientific workflow model. |
| JC-003 | 7 | Review calibration proposals and impact before mutation | High-value follow-on candidate with clear workflow improvement case evidence; useful for parameter proposal concepts and later bounded calibration automation. | First slice may validate proposal, impact, review, and shadow-loop evidence; real write-back, rollback, and autonomous calibration require accepted runtime, review, and audit boundaries. |
| JC-005 | 8 | Validate hardware bring-up | Real workflow and useful future pressure from wiring, registry, and driver initialization evidence. | Device communication, apply, and mutation are ADR-gated. |
| JC-007 | 9 | Preview, diff, and freeze experiment or queue intent | Tests PN-017 and scan semantics pressure that current artifacts cannot fully expose because the old workflow lacks a durable plan object; can also make notebook-cell or script-loop queue intent explicit before execution. | Intent preview only; no device apply, live scheduling, remote execution, unattended execution, or authoritative parameter ownership without a later runtime boundary. |
| JC-008 | 10 | Validate a dry-run or mock-queue execution package | Tests PN-018 by packaging code, context, generated artifacts, environment, expected outputs, queue order, and failure-policy evidence before execution. | Validation record only; no real worker fleet, shell-command product surface, remote execution, resource locking, or device control. |
| JC-011 | 11 | Watch a long-running measurement and produce replayable decision support | Tests TP-010 through PN-033, PN-034, PN-035, PN-036, and PN-037: consume explicitly recorded live or replayed measurement records without owning hardware control, detect completed analysis slices, show fit/quality/anomaly feedback, and record stop/continue/retune-style decision evidence that can feed later shadow automation. | Advisory or shadow-automation evidence only; no replacement live-plotting product, hardware control, scan-plan mutation, parameter write-back, autonomous calibration, opaque AI advice, passive scraping, framework-specific adapter matrix, or acquisition-path dependency. |
| JC-012 | 12 | Turn a small declared setup or local schema into useful context output | Tests PN-031 and PN-032: manually maintained physical, setup, topology, alias, attenuation, or experiment-schema context must earn its upkeep by powering lookup, calculation, visualization, comparability review, handoff, or diagnostics. | Useful output only; no universal setup ontology, exhaustive lab inventory, software-proof of physical truth, authoritative setup model, or high-ceremony metadata capture before visible value. |
| JC-013 | 13 | Diagnose shared code or configuration asset drift from a known-good source | Tests TP-009 through PN-006, PN-005, PN-018, PN-020, PN-021, PN-023, PN-024, PN-027, and PN-030: recover source identity, reusable layers, dependency readiness, drift, validation evidence, and diagnostic sharing boundaries for copied methods or runnable configuration. | Diagnostic and reuse evidence only; no Git hosting, package registry, deployment manager, automatic environment sync, code-review platform, authoritative config owner, or full work-bundle import. |
| JC-014 | 14 | Trace figure, report, fit, or claim impact back to source evidence | Tests PN-029 with PN-004, PN-010, PN-011, and PN-012: start from a derived analysis artifact and show source runs, processing code, correction choices, calibration context, setup assumptions, exclusions, reruns, and unresolved ambiguity that affect the claim. | Lineage and impact review only; no full ELN, report generator, publication workflow, managed analysis execution, automatic reanalysis, or claim correctness scoring. |
| JC-015 | 15 | Ordinary Python script to durable measurement record | Tests EV-012 and EV-045 with PN-009, PN-015, and PN-016: a normal script explicitly creates a run, declares data shape or sweep semantics, appends data in batches, records lifecycle state, survives ordinary interruption with checkpoint-safe reads, and reopens by stable ID. This closes the substrate gap behind `JC-002` reader realism and `JC-011` recorded-input decision support. | Durable recording substrate only; no managed runner, scheduler, hardware control, device apply, environment mutation, full live viewer, resumable execution promise, or storage/API contract beyond the fixture boundary. |
| JC-016 | 16 | One reviewed package to one lab-owned runtime for one bounded local run | Tests the bridge from `JC-007`, `JC-008`, `JC-003`, and `JC-011` into bounded real automation: a frozen plan, proposal, or queue package with runtime owner, supplied bounds, readiness evidence, review gates, lifecycle, stop behavior, failure policy, and audit records can be handed to one lab-owned runtime for one bounded local run. | First bounded runtime-handoff boundary only; no Scopecat-owned instrument runtime by default, generic scheduler, workflow DAG, environment sync, package deployment, broad resource-locking system, rollback guarantee, or autonomous calibration platform. |

## Anti-Patterns Not To Preserve

These are observed in raw material or legacy samples, but should not guide new
system design except as migration hazards, portability risks, or public-export
redaction risks.

| Anti-pattern | Why not preserve |
| --- | --- |
| LabRAD/Data Vault emulation, old-history import, or Data Vault browser/parser scope | The old mechanism is evidence and a migration fixture, not the target product model. |
| Latest-file, negative-ID, sorted-directory, counter, or timestamp identity | These are fragile discovery conventions, not durable identity semantics. |
| Direct notebook mutation of parameter or registry JSON | Calibration and configuration mutation need proposal, review, diff, and rollback boundaries. |
| Automatic notebook state capture | Notebook outputs and variable state are noisy, large, path-specific, and not a reliable provenance baseline. |
| Parsing arbitrary setup/wiring/registry files as trusted truth | Early Scopecat can show candidates and ambiguity; semantic ownership requires later models. |
| Treating declared physical wiring, sample topology, or attenuation as software-verified truth | These facts may be manually declared, inferred, stale, or externally evidenced; early records need source, freshness, validity, and verification status. |
| Exhaustive manual setup or chip-topology inventory before a useful output exists | Users are unlikely to maintain high-ceremony metadata unless it powers concrete lookup, calculation, visualization, comparison, handoff, or diagnostic workflows. |
| A fixed universal parameter, setup, or sample-topology schema as the first model | Experiment schemas evolve locally and are only approximately stable over bounded periods; start with versioned local schemas and aliases. |
| Treating behavioral or scaling priors as evidence | Priors are prompt tools for generating hypotheses; they should not raise confidence, rank pains, or define personas without fixture, interview, or observed workflow support. |
| Running only prior-informed role-play without a no-prior control | Priors can improve breadth but also bias answers toward messy exploratory labs, rescue workflows, superconducting-style wiring, anti-schema assumptions, and passive capture. |
| A Scopecat-owned config truth that silently diverges from scripts, control PCs, or lab notes | The tool should first expose source, freshness, ambiguity, and selected/proposed/applied status; authoritative ownership needs later contracts. |
| Folder-copy provenance, backup notebooks, embedded Git folders, checkpoints, and caches | These prove provenance pain; they are not acceptable provenance design. |
| Pickle or opaque binary files as preferred interchange | Treat as legacy artifacts unless a later decision accepts a safe format contract. |
| Data Vault bypass or CSV overwrite after primary record creation | Evidence of durability/source-of-record anxiety, not a pattern to normalize. |
| Local database commit/diff/reset helpers as the parameter model | Evidence for parameter-history pressure, but insufficient to define Scopecat parameter memory. |
| Unrecorded randomness or generated protocols without seeds/source metadata | Reproducibility requires protocol/design artifact provenance. |
| Metadata completeness or code-version capture presented as experiment trust | Provenance can create false confidence unless missing setup, calibration, operator, sample, and readiness gaps remain visible. |
| Replacing existing measurement/control/calibration frameworks as the default product story | Existing frameworks already solve many acquisition, metadata, control, scheduling, and calibration needs; Scopecat's early advantage should be complementary explanation, comparison, readiness, and handoff. |
| Treating JTBD candidates or capability gaps as evidence-backed pains | A journey job or desired capability can be important, but it still needs a top-level pain, fixture, and evidence route before it changes priority. |
| Presenting existing-framework baseline behavior as product differentiation | Durable run records, lifecycle state, source-of-record clarity, readable metadata, and stable identifiers are expected substrate unless tied to a stronger cross-stack pain. |
| Live dashboards on the write acknowledgement path | Live inspection should remain a disposable consumer. |
| Realtime feedback framed as prettier live plotting | Existing systems already provide many live plots, callbacks, dashboards, and browsers. Scopecat's differentiating pressure is passive, method-aware, replayable decision support for long-running measurements. |
| Measurement-time recommendations without replayable evidence | Stop, continue, retune, repeat, and zoom suggestions should cite data slices, metrics, thresholds, uncertainty, analysis configuration, and available-at-the-time context. |
| Treating watchdog recommendations as autonomous calibration or hardware-control authority | Measurement-time decision support may feed later calibration review, but first slice recommendations are advisory evidence, not parameter write-back, scan-plan mutation, or device apply. |
| Passive scraping or framework-specific auto-adapters as the live-observation model | Measurement-time decision support should start from explicit Scopecat recording by experiment code. Do not rely on polling instruments, importing live control scripts, reading mid-write files, or automatically adapting arbitrary measurement frameworks. |
| Mandatory cloud login, network service, heavy agent, or automatic Windows driver/environment mutation on control PCs | These are adoption and safety risks for scarce measurement windows; Journey selection should prefer read-only companion diagnostics until explicit decisions exist. |
| Automatic rollback, restore, or environment management as the first answer to known-good pressure | Known-good references should first support comparison and diagnostics; mutation and restore semantics require later decisions. |
| Generic workflow DAGs, schedulers, queues, shell-command runners, device apply, or AI mutation | These need later scope validation and ADR/review boundaries. |

## Saturation Assessment

The recurring directly visible evidence pass categories are saturated enough for journey
drafting:

- selected context, ambiguity, and portability;
- code/notebook provenance;
- local runtime readiness;
- run identity and companion artifacts;
- generated protocol, correction, and run-family lineage;
- calibration/configuration mutation pressure;
- analysis handoff and derived artifacts;
- shape and lifecycle validation cases;
- anti-patterns that should not be preserved.

Future journey work should not need another broad pass over those categories before
drafting a journey. This saturation claim applies to artifact-derived
categories, not to adoption-risk hypotheses, cross-lab demand, role behavior,
or market differentiation. Remaining research should target exact examples,
citations, fixtures, or latent workflow validation: JTBD conversion, plan
preview, dry-run packaging, campaign-level comparison, scientific comparability,
full-stack known-good diffs, setup-reality maps, useful declared physical
context, local schema evolution, calibration impact, analysis/publication lineage,
manual-intervention memory, behavioral-prior prompt artifacts,
existing-framework baseline separation, control-PC read-only companion
constraints, known-good references, boundary-aware diagnostic packages,
measurement-time decision support, resource coordination, and automation after
reliable automatic versioning.
