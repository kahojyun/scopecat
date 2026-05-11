# Research Acceptance Readiness Triage

## Status

Transitional

## Source

- [`../greenfield-experimental-automation-architecture-notes.md`](../greenfield-experimental-automation-architecture-notes.md):
  raw historical architecture discussion for a progressively adoptable
  experimental automation platform.
- [`../raw/fricon-legacy-docs/README.md`](../raw/fricon-legacy-docs/README.md):
  raw predecessor documentation import.
- High-value files inside the Fricon import, especially:
  - [`source/docs/product/vision.md`](../raw/fricon-legacy-docs/source/docs/product/vision.md)
  - [`source/docs/product/personas.md`](../raw/fricon-legacy-docs/source/docs/product/personas.md)
  - [`source/docs/product/story-map.md`](../raw/fricon-legacy-docs/source/docs/product/story-map.md)
  - [`source/docs/product/capability-map.md`](../raw/fricon-legacy-docs/source/docs/product/capability-map.md)
  - [`source/docs/product/product-analysis-progress.md`](../raw/fricon-legacy-docs/source/docs/product/product-analysis-progress.md)
  - [`source/docs/research/legacy-measurement-sample-lessons.md`](../raw/fricon-legacy-docs/source/docs/research/legacy-measurement-sample-lessons.md)
  - [`source/docs/research/lessons-for-fricon.md`](../raw/fricon-legacy-docs/source/docs/research/lessons-for-fricon.md)
  - [`source/docs/research/strategic-follow-on-future-systems.md`](../raw/fricon-legacy-docs/source/docs/research/strategic-follow-on-future-systems.md)
  - [`source/docs/architecture/README.md`](../raw/fricon-legacy-docs/source/docs/architecture/README.md)
  - [`source/docs/architecture/compatibility-policy.md`](../raw/fricon-legacy-docs/source/docs/architecture/compatibility-policy.md)
  - [`source/docs/decisions/ADR-001-v02-clean-reset-boundary.md`](../raw/fricon-legacy-docs/source/docs/decisions/ADR-001-v02-clean-reset-boundary.md)

## Summary

This note classifies raw research by acceptance readiness. It is intended as a
future entry point before reading raw Fricon or greenfield notes.

It does not accept product scope or architecture by itself. It separates:

- claims that are safe to accept now as project guardrails;
- high-quality factual background and evidence;
- evidence-backed inferences that are strong early acceptance candidates;
- adoption hypotheses that still need journey validation;
- future pressure that should constrain early design without becoming first
  scope;
- ADR-gated or explicitly rejected directions.

## Extracted To

- [`../research-index.md`](../research-index.md) records this extracted note.
- [`../../document-index.md`](../../document-index.md) lists this note as the
  preferred entry point for raw research triage.
- [`../../progressive-adoption-progress-tracker.md`](../../progressive-adoption-progress-tracker.md)
  may use this note as the output of the first research-distillation step.
- [`../../evidence-and-pain-point-inventory.md`](../../evidence-and-pain-point-inventory.md)
  summarizes the W1 evidence, pain, guardrail, baseline, and source-hygiene
  claims for W2 source-map and journey work.

## Remaining Value

Raw research remains useful for provenance, exact source context, detailed
examples, external reference links, and later extraction into journey, pain,
capability, domain, architecture, or ADR documents.

Do not read this note as a replacement for user validation. Use it to decide
which claims can be accepted early, which can be cited as evidence, and which
must remain hypotheses until promoted into an owning durable document.

Delete or archive this note after W2 selects and validates the first journey
and any still-useful guardrails, hypotheses, future pressures, and ADR triggers
have moved into narrower owner documents. It should not remain a regular
entry point once W1/W2 docs can explain the accepted evidence and current
questions directly.

## Validation Updates

[`legacy-experiment-code-sample-validation.md`](legacy-experiment-code-sample-validation.md)
validates this triage against two copied legacy experiment codebases. It
supports the main claims and adds refinements around generated-sidecar
reconciliation, analysis handoff, dependency/environment manifest pain,
hardware bring-up validation, readout/SPAM provenance, notebook/repository
hygiene, and portability/sanitization as product support.

Use the validation note before promoting pain points or journeys from those
sample codebases.

## Acceptance Readiness Classes

| Class | Meaning | Handling |
| --- | --- | --- |
| Accepted guardrail | Project operating rule or design guardrail that is already consistent with current Scopecat docs. | Use immediately unless a later durable doc changes it. |
| Evidence/background | High-quality source observation or reference finding. | Cite as evidence; do not turn it into product scope without a promoted claim. |
| Evidence-backed inference | Reasoned conclusion supported by multiple evidence inputs. | Candidate for early acceptance after owner review and placement in the narrowest durable doc. |
| Adoption hypothesis | Plausible capability, first slice, ordering, UX shape, or migration path. | Validate against a concrete current journey before promotion. |
| Future pressure | Long-term capability pressure that early models should leave room for. | Keep visible during domain and architecture work; do not implement from this note alone. |
| ADR-gated | Direction with safety, compatibility, storage, mutation, distributed, or automation risk. | Requires explicit ADR or equivalent durable decision before scope acceptance. |
| Do not accept upfront | Direction rejected for first adoption or too speculative for current work. | Keep out of initial scope unless new evidence and a durable decision reverse it. |
| Open question | Important unresolved decision. | Track in the next journey, validation plan, spike, ADR, or capability note. |

## Accepted Guardrails

These are safe to accept up front because they describe how Scopecat should
process research and shape early work, not because they accept a product slice.
Treat them as project process or documentation guardrails unless separate
journey evidence promotes the same claim as product scope.

| Claim | Why it is ready | Handling |
| --- | --- | --- |
| Raw research is not product or architecture truth. | Current research policy already defines `raw input -> extracted claim -> promoted durable doc`. | Keep this as the default rule for all raw Fricon and greenfield material. |
| Use journey-first discovery before subsystem specs. | Current docs already require journey-first product discovery and shared pain-point artifacts. | Do not create subsystem specs from raw capability maps. |
| Use progressive adoption instead of big-bang migration. | Both current Scopecat docs and raw research converge on incremental adoption. | Treat this as an early product/architecture guardrail. |
| Each foundational capability needs standalone user value before composition. | This follows from progressive adoption and reduces migration risk. | Use as a heuristic when evaluating capability candidates; do not treat the current capability map as accepted. |
| Keep accepted facts in the narrowest owning durable document. | Current docs policy already says to promote out of research. | Use this note as triage, then promote only narrow claims. |
| Keep public/user documentation redacted by default. | Existing repo instructions require public-docs redaction; W1 reframes internal local context primarily as portability and reuse evidence. | Do not leak local paths, lab identifiers, or private interview details into public docs; do not promote internal redaction workflows without user evidence. |
| Avoid broad scaffolds before content exists. | Existing docs policy forbids placeholder lifecycle folders and broad docs scaffolds. | Do not copy the greenfield subsystem document tree unless real accepted content justifies it. |

## Evidence And Background

These are strong factual inputs. They can be used as evidence immediately, but
they do not by themselves decide Scopecat product scope.

| Evidence | Source strength | Suggested use |
| --- | --- | --- |
| Legacy measurement identity is scattered across Data Vault paths, numeric IDs, notebooks, sidecars, copied parameter files, and local folder conventions. | Concrete user-supplied legacy sample review, redacted for local identifiers. | Use as pain evidence for measurement identity and stable reopen work. |
| Lab runtime context is machine-local and often constrained by Windows, offline or locked-down machines, pinned environments, driver paths, static IPs, services, and operator memory. | Legacy sample review plus Fricon persona grounding. | Use as evidence for local product readiness and diagnostics. |
| Code provenance is often folder-copy based, with backups, nested package snapshots, dated JSON, generated caches, and partial Git use. | Legacy sample review. | Use as evidence for code provenance pressure; do not jump directly to a managed code platform. |
| Parameters and setup context are mutable files such as parameter JSON, registry JSON, wiring sheets, line/chip summaries, demod/readout settings, generated sidecars, and temporary files. | Legacy sample review. | Use as evidence for run-bound context snapshots, later parameter memory, and ambiguity handling. |
| Analysis often reconstructs scan meaning after acquisition from column order, filenames, sidecars, and notebook-local arrays. | Legacy sample review and VNA analysis pressure. | Use as evidence for explicit scan and trace shape semantics. |
| Calibration work already mixes measurement evidence, fits, generated files, parameter edits, routine health, and operator judgment. | Legacy sample review and strategic follow-on research. | Use as evidence for future reviewable calibration and parameter proposals. |
| Partial or interrupted acquisition is currently treated as cleanup/debugging rather than a first-class readable lifecycle state. | Legacy sample review. | Use as evidence for checkpoint-safe readability and visible incomplete states. |
| VNA traces, IQ/readout data, single-shot arrays, complex values, coarse/fine traces, and irregular or minimizer records are real data-shape pressures. | Fricon interview passes and sample-code pressure. | Use as validation cases for data shape, reader, and live inspection decisions. |
| Existing systems support both run/measurement records and dataset-level access. | External reference synthesis across QCoDeS, LabRAD, Bluesky/Tiled, Labber, ARTIQ, and related systems. | Use as background for keeping measurement-centered UX and dataset artifacts first-class. |
| Existing systems treat partial/interrupted data, lifecycle, event streams, setup snapshots, export, and callbacks as recurring concerns. | External reference synthesis. | Use as background checks, not as a mandate to copy any one system. |

## Early Acceptance Candidates

These are evidence-backed inferences that look strong enough to review early.
They should be promoted only after a current Scopecat owner decides the target
doc and status.

| Candidate claim | Evidence basis | Suggested promotion target |
| --- | --- | --- |
| Measurement identity and dataset artifacts should both be early durable concepts. | Legacy identity scatter, external references, and Fricon story/capability maps all point here. | Future journey, capability, or concept docs. |
| The first concrete journey should likely include ordinary Python writing durable data, simple live inspection, checkpoint-safe readability, and stable-ID reopen. | Fricon interview evidence and the current progressive-adoption tracker both name this as a candidate wedge. | Journey selection note before capability acceptance. |
| Dataset shape semantics should cover regular grids, partial grids, irregular/ragged records, trace-valued records, multiple traces per outer record, and first-class complex/IQ values. | VNA, IQ/readout, and minimizer evidence repeatedly stress these shapes. | Dataset/measurement concept doc after journey selection. |
| Live inspection should be a disposable consumer, not part of write acknowledgement. | External references and acquisition-risk reasoning both support keeping writes primary. | Architecture guardrail or capability note. |
| Checkpoint-safe readability should precede resumable execution. | Readable partial data is a direct user pain; resumability requires managed execution semantics. | Journey/capability doc, with resumability deferred or ADR-gated. |
| Stable-ID reopen should precede polished portable export. | The observed immediate analysis task is local Python reopen; export is still important but less first-contact. | Measurement history or reader capability note. |
| Passive, honest context should come before managed truth. | Legacy context is useful but opaque; early product should not claim to own setup, wiring, parameters, or notebook state without evidence. | Provenance or attachment concept note. |
| Dataset artifacts should remain searchable and directly openable even if Desktop becomes measurement-centered. | External systems and Fricon docs both show users need dataset-level access. | UX/capability doc. |
| Local product readiness and fail-before-write compatibility checks matter early. | Lab machines are constrained and data mutation must be safe. | Architecture compatibility doc or ADR. |
| Mutation of parameters, setup, devices, data-library state, or AI-assisted actions should be previewable, reviewable, and auditable. | Legacy calibration risk and strategic follow-on research both point to hidden mutation as high risk. | Future ADRs and capability docs. |

## Adoption Hypotheses

These are plausible but not ready for upfront acceptance.

| Hypothesis | Why not accept yet | Next validation |
| --- | --- | --- |
| Six foundational capabilities plus two composition capabilities are the right map: Measurement History, Scan Framework, Parameter Memory, Code Asset Registry, Instrument Runtime, Managed Code Runner, Workflow, Remote Execution. | This came from a greenfield architecture discussion, not an accepted Scopecat product baseline. | Map the first selected journey to capabilities and only keep boundaries that explain real work. |
| Measurement History should be the first implementation path. | Fricon made measurement history central, but Scopecat intentionally broadened the model. | Compare against scan, parameter, code provenance, runtime, and runner pain before choosing. |
| A likely migration order is Measurement History, Scan Framework, Parameter Memory, Instrument Runtime, Code Asset Registry, Managed Code Runner, Workflow, Remote Execution. | The greenfield note explicitly says ordering should be driven by interviews. | Use evidence-ranked migration wedges, not a subsystem-preference order. |
| The Python SDK should expose a specific context-manager, scan-plan, trace-writer, or managed-run shape. | Current SDK examples are UX sketches and exact names/signatures are deferred. | Test with real translated scripts and promote API decisions through specs or ADRs. |
| Reader adapters should target Polars, pandas, NumPy, xarray, or specific default views. | Research identifies pressures but does not settle the reader contract. | Start from concrete analysis tasks and choose minimum useful views. |
| Feature flags and experimental namespaces are the right maturity mechanism. | Useful idea, but not tied to an accepted release or API compatibility plan. | Revisit when public API surfaces and capability maturity differ in implementation. |
| The greenfield subsystem document tree should become the docs structure. | Current Scopecat policy rejects broad scaffolds before accepted content exists. | Create only the narrow documents needed by promoted claims. |

## Future Pressure To Preserve

These should influence early concept and architecture shape, but they are not
first-scope commitments.

| Pressure | Preserve room for | Do not do from this note alone |
| --- | --- | --- |
| Parameter memory | Immutable run-bound snapshots, named profiles, diffs, proposals, rollback targets, and review history. | Full global parameter registry or device write-back. |
| Code asset provenance | External repo/package/local-folder references, commits, entrypoints, code snapshots, and provenance levels. | Git hosting, package registry, or forced managed execution. |
| Managed execution | Logs, status, artifacts, environment summaries, process supervision, and execution records. | Scheduler, queue, generic shell launcher, or remote runner as first UX. |
| Calibration evidence | Task health, fitted values, affected paths, chain working refs, proposals, and reviewed promotion. | Direct durable parameter mutation or hidden automation. |
| Setup and device state | Desired versus observed state, readbacks, reconciliation diffs, apply plans, and audit records. | Broad device framework or apply semantics without safety decisions. |
| Analysis and handoff | Derived artifacts, fit outputs, plots, reports, spreadsheets, interpretation notes, and provenance back to source runs. | Full ELN, LIMS, or report-generation product. |
| Export and offline access | Read-only bundles, manifests, checksums, source identity, and later common analysis formats. | Export-first success path before local reopen works. |
| Remote execution | Immutable packages, revalidation, leases, exact code and parameter resolution, monitoring, and cancellation. | Remote coordinator or security model before local journey scope is clear. |
| Sample maps and spatial views | User-authored sample-map configs and visual query views. | A full physical sample ontology as an early model. |

## ADR-Gated Or Do Not Accept Upfront

These directions require explicit decisions or should stay out of first
adoption unless new evidence changes the project baseline.

| Direction | Class | Reason |
| --- | --- | --- |
| Device communication or mutation. | ADR-gated. | Live hardware mutation has safety, readback, timing, and audit implications. |
| Setup/device desired-state apply or reconciliation. | ADR-gated. | Desired state, observed state, and apply status must stay distinct. |
| Mutation-capable calibration automation. | ADR-gated. | Hidden parameter or setup mutation is a central product risk. |
| Resumable execution checkpoints. | ADR-gated. | Requires managed runner, scan-point semantics, and recovery contracts. |
| Distributed or shared editable data libraries. | ADR-gated. | Introduces consistency, locking, and deployment semantics outside first local scope. |
| Third-party protocol or legacy format compatibility promises. | ADR-gated. | Compatibility claims can lock the wrong user model into place. |
| AI-assisted mutation of durable state. | ADR-gated. | Requires preview, review, audit, and rollback decisions. |
| Hosted SaaS, accounts, teams, or permissions. | Do not accept upfront. | Current evidence is local-lab migration-focused; hosted collaboration has no first-slice evidence. |
| LabRAD compatibility server, helper module, old-history import, or old Data Vault browser. | Do not accept upfront. | Legacy mechanisms should be aliases, context, attachments, summaries, or evidence unless a later migration ADR says otherwise. |
| Broad device-driver framework. | Do not accept upfront. | Passive setup/procedure context is enough before instrument runtime is validated. |
| Generic workflow DAG engine. | Do not accept upfront. | Workflow should compose mature capabilities, not drive first adoption. |
| Automatic notebook state capture. | Do not accept upfront. | Research says output cleanup, folder size, and variable-state recovery are poor first-slice value. |
| Treating physical setup notes, wiring files, or opaque config as Scopecat-owned truth. | Do not accept upfront. | Early product can record evidence without judging freshness or correctness. |
| Internal streams as the normal user-facing concept. | Do not accept upfront. | Streams may be useful internally; dataset artifacts are the clearer user concept. |
| Exact API syntax from research sketches. | Do not accept upfront. | Sketches capture UX intent only. |

## Open Acceptance Questions

- Which concrete current Scopecat journey should be analyzed first?
- Is write/watch/reopen still the best first journey after comparing scan,
  parameter, code provenance, runtime, and runner pain on equal terms?
- Which validation case should challenge the VNA/readout-heavy evidence?
- What success signals prove that the first adoption slice is useful enough?
- Which dataset reader view should be first-contact, and which should remain
  alternate conversion methods?
- Which shape semantics are required for the first journey, and which are only
  future pressure?
- What is the minimum passive provenance model that is useful without becoming
  a false setup, parameter, or code truth system?
- Which claims should become ADRs before any implementation work starts?

## Suggested Next Promotion Sequence

1. Promote the high-quality evidence into a compact evidence and pain-point
   inventory.
2. Select one current-state and future-state journey using that evidence.
3. Decide whether the write/watch/reopen wedge is accepted, rejected, or kept
   as one candidate among several.
4. Promote only the capabilities touched by that journey into adoption-ladder
   or capability notes.
5. Capture minimal domain concepts and contracts for the selected wedge.
6. Write ADRs before any mutation, compatibility, storage durability,
   distributed, remote execution, or AI-assisted action commitment.
