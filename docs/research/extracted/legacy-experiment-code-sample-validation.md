# Legacy Experiment Code Sample Validation

## Status

Transitional

## Source

Read-only review of a local internal workflow-improvement repository outside
this repository on 2026-05-11.

The sample contains two copied legacy experiment code trees:

- Tree A: an acquisition, configuration, setup, and sidecar-heavy code tree.
- Tree B: an analysis, handoff, and publication-artifact-heavy code tree.

The source tree is not copied into this repository. Treat it as internal
research evidence. Paths, machine details, instrument addresses, local users,
and lab identifiers should be described conceptually before reusable examples
are derived from it, and redacted before any public documentation use.
Exact local paths, tree names, system labels, sample labels, and lab-specific
identifiers are intentionally omitted here. If W2 needs to recover exact
provenance, keep that mapping in a non-public fixture source map rather than in
this public extracted note.

Notebook review used code-cell extraction only. Notebook outputs were not used
as evidence because many notebooks contain uncleared output.

## Summary

The sample strongly validates the prior acceptance-readiness triage in
[`research-acceptance-readiness-triage.md`](research-acceptance-readiness-triage.md).

It also sharpens the next research model. The strongest refinement is that
legacy pain is not only "measurement history" or "parameter drift." The
observed workflow is more often:

```text
Data Vault run
  -> generated sidecars
  -> mutable setting files
  -> notebook-runbook analysis
  -> derived arrays, figures, spreadsheets, or decks
  -> manual parameter or registry mutation
```

The previous triage remains broadly correct, but this sample raises the
priority of generated-sidecar reconciliation, analysis handoff, hardware
bring-up validation, dependency/environment manifest pain, readout/SPAM
provenance, notebook/repository hygiene, and portability/reuse hygiene.

## Current Use

[`research-acceptance-readiness-triage.md`](research-acceptance-readiness-triage.md)
remains the broader acceptance-readiness triage; this note validates and
refines it with direct code-sample evidence.
[`../../evidence-and-pain-point-inventory.md`](../../evidence-and-pain-point-inventory.md)
summarizes the public-safe W1 evidence and W2 fixture-source-map requirements
derived from this validation.

## Remaining Value

The internal sample and this validation note still have value for later
detailed extraction into:

- evidence and pain-point inventory;
- current-state journeys;
- dataset and sidecar concept work;
- parameter proposal and calibration evidence work;
- environment/dependency manifest work;
- analysis handoff and derived-artifact lineage work;
- hardware bring-up and portable setup-context work.

Use exact source files when working internally, but do not bake local paths,
IPs, instrument identifiers, or lab-specific labels into reusable examples or
public docs.

Delete or archive this note after W2 has selected the first journey and moved
any still-useful validation cases into journey fixtures, capability/adoption
hypotheses, architecture questions, or ADR triggers. Keep the note longer only
if the local code sample is no longer available and this file is the only
remaining provenance for a claim.

## Method

The review combined local inspection with three subagent passes:

- Tree A validation;
- Tree B validation;
- cross-cutting repository inventory and pattern review.

Notebook code cells were extracted with commands equivalent to:

```sh
jq -r '.cells[] | select(.cell_type=="code") | .source[]?' notebook.ipynb
```

This avoided treating stale notebook output as evidence.

## Inventory Signals

The exact counts are evidence about repository shape, not product
requirements.

| Signal | Finding | Interpretation |
| --- | --- | --- |
| Top-level copied trees | Two experiment code trees under the sample root. | Evidence for copied-code provenance and branch/fork ambiguity. |
| Notebooks | 99 notebooks total; most have output or execution counts. | Notebook state is operationally important but noisy as an automatic capture target. |
| Python files | 591 `.py` files plus 226 `.pyc` files. | Code, caches, and generated artifacts are mixed in the working tree. |
| Settings and configs | Many JSON, INI, lock, CSV, and XLSX files under `setting/`, `backup/`, `spectrum/`, and `temp/`. | Strong evidence for mutable configuration drift and uncertain source of truth. |
| Data and sidecars | CSV, NPY, NPZ, PKL, TXT, PNG, ZIP, PPTX, PDF, and notebook artifacts. | Measurement meaning often extends beyond one primary dataset. |
| Embedded or copied provenance | Duplicated package trees, backup folders, zip snapshots, and embedded Git folders. | Code identity is not cleanly represented by one Git repository. |
| Local dependencies | Code imports unavailable or environment-specific packages such as public instrument libraries, local helper packages, hardware drivers, instrument services, database helpers, and wave viewers. | "Can I run this here?" is an environment-manifest pain before it is an instrument-control pain. |

## Validated Claims

| Prior triage claim | Validation result | Evidence pattern |
| --- | --- | --- |
| Measurement identity is scattered. | Strongly supported. | Data is reopened by Data Vault folder plus numeric ID, `idxNNNNN` filenames, numeric CSV prefixes, notebook variables, and generated sidecars. |
| Dataset artifacts should remain first-class. | Strongly supported. | Runs produce CSV/INI pairs, IQ arrays, probability tables, tomography tensors, feedback records, VNA traces, and analysis summaries. |
| Stable reopen matters early. | Supported, but insufficient alone. | Numeric IDs reopen raw data, but meaningful analysis also needs parameter snapshots, readout correction, sidecars, selected run ranges, and notebook-local constants. |
| Dataset shape semantics need breadth. | Strongly supported. | Evidence includes regular grids, repeated runs, traces, shot arrays, IQ data, probability columns, tomography/QPT/QST arrays, feedback records, and ragged derived records. |
| Parameter and setup drift are real pain. | Strongly supported. | Parameter JSON, registry JSON, wiring spreadsheets, spectro-bias CSVs, generated temp JSON, and dated backups coexist. |
| Calibration needs reviewable evidence before mutation. | Strongly supported. | Notebook and script workflows fit values, update JSON fields, compare prior values, and save back without a durable proposal/review boundary. |
| Passive setup and procedure context should precede managed truth. | Strongly supported. | Settings contain wiring, registry, line/chip, mixer, demod, crosstalk, predistortion, and instrument connection context that should be evidence before trusted owned state. |
| Code provenance should start as evidence, not managed execution. | Strongly supported. | Duplicated modules, backups, zip snapshots, checkpoints, copied packages, and embedded Git folders make "which code produced this?" a first-class evidence problem. |
| Automatic notebook state capture should not be accepted upfront. | Strongly supported. | Notebooks are output-heavy, path-specific, branchy, and often act as mutable operational runbooks. Code-cell extraction and explicit linking are more plausible early moves. |

## Refinements To The Triage

The following items should be added or emphasized in future promotion work.

| Refinement | Why it matters | Acceptance readiness |
| --- | --- | --- |
| Generated-sidecar reconciliation | Data Vault records often need matching `.npz`, `.json`, copied parameter snapshots, generated dictionaries, feedback records, or derived arrays to be understandable. | Early acceptance candidate as a measurement-history/attachment pressure. |
| Analysis handoff as its own journey | Tree B has a handoff bundle from raw runs to summary CSV/NPY data, figure notebooks, and presentation/publication artifacts. | Early journey candidate; product shape still hypothesis. |
| Dependency/environment manifest pain | Missing local packages and services block import and understanding before any hardware is touched. | Early evidence candidate; exact managed-run solution remains hypothesis. |
| Hardware bring-up validation | Wiring spreadsheet -> registry -> instrument driver connection is a real workflow with safety and portability implications. | Future pressure; device communication and mutation remain ADR-gated. |
| Readout/SPAM correction provenance | Tomography and fidelity work depend on readout matrices, IQ references, correction arrays, and manual choices. | Strong evidence for derived-artifact lineage; exact product model is hypothesis. |
| Notebook/repository hygiene | Uncleared outputs, checkpoints, caches, embedded Git packs, zip snapshots, and generated binaries are large operational clutter. | Evidence/background; do not jump to automatic notebook capture. |
| Portability and sanitization as product support | Local paths, shares, machine/service details, and instrument addresses are common in evidence. | Early guardrail for reusable examples, handoff/export design, and public-doc redaction. |

## Additional Plausible Pain Points

| Pain point | Evidence pattern | Current classification |
| --- | --- | --- |
| Which file is the truth? | Multiple `parameters*.json`, `registry*.json`, dated backups, lock files, generated temp files, and spectrum/wiring spreadsheets. | Evidence-backed inference. |
| Can I reopen and explain this result? | Raw dataset IDs do not carry every sidecar, parameter snapshot, readout correction, or notebook-local choice needed for interpretation. | Evidence-backed inference. |
| Can I run this code on another machine? | Imports and services depend on local instrument-control services, driver packages, local paths, network-visible instruments, and private helper packages. | Evidence-backed inference. |
| Which code version produced the run? | Active modules, backups, old copies, checkpoint folders, zip snapshots, and embedded Git repositories coexist. | Evidence-backed inference. |
| How do I review calibration changes before they mutate settings? | Calibration notebooks fit values and write JSON fields directly, sometimes with commented alternatives. | Early acceptance candidate for reviewable proposals; implementation deferred. |
| How do I link reports and figures back to source runs? | Presentation decks, spreadsheets, NPY summaries, figure notebooks, and publication artifacts sit beside raw and processed data. | Early journey candidate. |
| How do I know a sidecar set is complete? | Sidecars are named by dataset counter or local convention and may be written after primary data. | Evidence-backed inference. |
| How do I clean, reuse, or share a run safely? | Local paths, service addresses, notebook output, generated caches, and reports are intermingled. | Evidence-backed inference and portability guardrail; redaction applies for public export. |
| Which notebook/script branch actually produced this output? | Backup notebooks, old scripts, checkpoint files, and commented path alternatives create branch ambiguity. | Evidence-backed inference. |

## Additional Plausible Journeys

These are not accepted product scope. They are candidates for journey-first
validation.

| Journey candidate | Current-state sketch | Potential Scopecat value |
| --- | --- | --- |
| Reopen a run with sidecars | User starts from a Data Vault numeric ID or `idx` file, then hunts for parameter snapshots, `.npz` arrays, `.json` records, notebook code, and figures. | One stable run entry point lists primary dataset, sidecars, settings snapshots, derived artifacts, and provenance coverage. |
| Review calibration before mutation | User runs calibration code, fits values, edits `parameters.json`, and maybe keeps backups or comments. | Calibration result becomes a proposal with source run, fit output, before/after diff, reviewer decision, and rollback target. |
| Explain settings for a historical run | User reconstructs registry, parameters, spectro-bias, wiring, demod/readout, generated line/chip JSON, and code context. | A run-bound context snapshot shows what was recorded, what is opaque evidence, and what is missing or ambiguous. |
| Publish or hand off analysis | User packages raw IDs, summary CSV/NPY arrays, tomography/QPT code, figures, and slides. | Derived artifacts cite source runs, parameter snapshots, readout correction evidence, code context, and manual decisions. |
| Validate hardware bring-up | User converts wiring spreadsheets into registry entries, starts instrument services, checks connections, and calibrates LO/mixer/board state. | Portable setup manifest and diagnostics before any device mutation; apply/control remains ADR-gated. |
| Recover from latest-ID ambiguity | User relies on directory counters, latest numeric CSV prefixes, or `session.ini` to find what just ran. | Stable IDs and completeness checks reduce reliance on "latest" conventions. |
| Clean notebook/run provenance | User wants to know which notebook cell, script copy, or backup branch produced a result. | Link code snapshot or code-cell extraction as evidence without accepting full notebook state capture. |
| Navigate run families | Feedback and error-correction-style workflows create round-indexed records, state mappings, and correction artifacts. | Run-family navigation groups related runs, rounds, sidecars, and derived records. |

## Acceptance Readiness Updates

| Item | Updated class | Rationale |
| --- | --- | --- |
| Measurement identity plus dataset artifacts | Early acceptance candidate | Revalidated by both trees and by Data Vault helper conventions. |
| Stable reopen | Early acceptance candidate, narrowed | It should mean "reopen result plus explainability context," not only `DIR + numeric id`. |
| Generated sidecar attachment/provenance | Early acceptance candidate | Too common and too close to measurement interpretation to leave as vague future pressure. |
| Analysis handoff | Early journey candidate | Tree B shows a distinct raw-run-to-publication/report flow. |
| Dependency/environment manifest | Early evidence candidate | Environment pain exists before managed execution is justified. |
| Notebook-aware UX | Hypothesis | Code-cell extraction and linking look useful; full notebook state capture remains rejected upfront. |
| Parameter memory | Future pressure with early proposal evidence | Direct JSON mutation is common, but the first accepted model should likely be reviewable proposals rather than a full registry. |
| Hardware bring-up | Future pressure, partly ADR-gated | Diagnostics and portable manifests are plausible; device control and apply require ADRs. |
| Managed code runner | Future pressure | Code provenance is strong evidence, but copied-code identity should precede managed execution. |

## Suggested Next Promotion Work

1. Promote an evidence and pain-point inventory that includes the new
   sidecar, handoff, environment, and hygiene pain.
2. Select one journey to write in current-state and future-state form. The
   strongest candidates after this validation are:
   - reopen a run with sidecars;
   - review calibration before mutation;
   - publish or hand off analysis.
3. Update the acceptance-readiness triage after the journey choice so it
   reflects which refinements are accepted and which remain only candidates.
4. Keep hardware mutation, calibration write-back, setup apply, remote/shared
   libraries, and AI-assisted edits behind ADRs.
