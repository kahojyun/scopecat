# Selected Reference Comparison

## Status

Evidence-backed problem brief.

## User-Facing Failure

Users can often reopen a run or inspect a code bundle, but they still cannot
tell what changed against a selected reference: setup, sample, calibration,
generated protocol, environment, or analysis context. That reference may be
last-working, notable, best-observed, or simply relevant. The first useful
output is a practical comparison findings report over recorded context. User
scripts or humans interpret those findings.

## Observed Sample Evidence

- Workflow evidence contains wiring sheets, registry and parameter files,
  generated summaries, driver initialization, local paths, setup diagnostics,
  calibration artifacts, correction branches, and copied working folders.
- Existing framework baselines show strong stack-local run, metadata,
  snapshot, scheduler, and calibration support, but they do not settle the
  cross-stack explanation layer for inherited scripts and handoff bundles.
- Sample artifacts show many ways a result can depend on context outside the
  primary measurement row: generated protocols, readout correction, classifier
  choices, notebook-local constants, selected run ranges, and derived arrays.

## Project-Owner Clarification

- References such as last-working or notable can often be represented as
  ordinary user marks or labels on measurement records. Scopecat does not need
  special reference handling before it can compare records selected through
  those marks.
- Routine same-sample work usually stays on one setup; cross-setup value is
  more plausible for screening, setup comparison, handoff, or exceptional
  protocol-transfer cases.
- Same-station and NAS/shared-folder context may help records move across
  computers, but that does not imply remote execution, central storage, or a
  distributed control system.
- Internal diagnostic support may need local paths, hostnames, instrument
  addresses, and LabRAD or VISA details, while public docs or external handoff
  require different redaction boundaries.

## Derived Hypotheses

- A useful first comparison output may be a comparison findings report against a
  selected reference, not a user-judgment engine.
- The first reference-selection model can start from generic user marks on
  measurement records. Last-working, notable, and best-observed are useful
  labels, not necessarily dedicated Scopecat concepts.
- The first validated fixture should compare declared context around a current
  measurement and selected reference: named input snapshots, declared preview
  metadata, selected artifacts, and redaction/verification state.
- Experiment code/version mismatch is an important comparison dimension. It
  can be compared first as declared recorded-code context using the minimum
  recorded-code reference shape validated by experiment-code-recording, without
  inspecting Git state, restoring environments, or executing code.
- Compatible declared preview metadata may later support quick multi-measurement
  browsing or overlay for comparison. This is an inspection aid, not a
  publication-grade plotting or interpretation goal.
- Comparison findings should distinguish changed, missing, unverified,
  redacted, unlinked, same-observed, and not-compared facts instead of using
  "gap" as a catch-all.
- Setup and topology records only earn their keep if they support lookup,
  calculation, visualization, comparison, handoff, or diagnostics.
- Recipient-aware sharing is a separate product question from public-safe
  redaction.

## Out Of Scope For This Brief

- Scopecat-owned setup truth, user-judgment scoring, rollback, deployment,
  remote support, and managed environment mutation.
- Universal physical setup ontology, universal parameter schema, and
  hardware-resource arbitration.
- Treating context comparison as a substitute for user analysis or domain
  judgment.

## Possible Validation Questions

- Can users decide what changed, what is missing, unverified, redacted,
  unlinked, same-observed, or not compared from a selected reference comparison
  without Scopecat claiming setup truth or interpreting the result for them?
- Which diagnostic facts are safe and useful for internal support, and which
  must be omitted or redacted for public/exported artifacts?

## Finding Vocabulary

Use these labels when a comparison needs more precision than "same" or
"different":

| Finding | Meaning |
| --- | --- |
| Changed | Both sides expose the fact, and the observed values differ. |
| Missing | A needed fact or artifact is absent on one side. |
| Unverified | A fact is declared or implied but cannot be checked from available software evidence. |
| Redacted | A fact exists but is intentionally hidden for recipient, policy, or publication safety. |
| Unlinked | An artifact exists, but its source relation is uncertain. |
| Same observed | Both sides expose the fact, and the observed values match. |
| Not compared | The comparison is out of scope, unsupported, or intentionally skipped. |
