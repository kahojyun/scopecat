# Diagnostics And Comparability

## Status

Evidence-backed pain packet. Not a validation charter, diagnostic schema,
setup model, equivalence score, rollback design, or support workflow contract.

## User-Facing Failure

Users can often reopen a run or inspect a code bundle, but they still cannot
tell whether the current setup, sample, calibration, generated protocol,
environment, or analysis context is comparable to a known-good reference. This
creates a trust problem: two results may look valid locally while differing in
facts that matter scientifically or operationally.

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

- A useful first diagnostic output may be a gap or change report against a
  selected known-good reference, not a claim that two setups are equivalent.
- Setup and topology records only earn their keep if they support lookup,
  calculation, visualization, comparison, handoff, or diagnostics.
- Recipient-aware sharing is a separate product question from public-safe
  redaction.

## Premature / Do Not Promote Yet

- Scopecat-owned setup truth, automatic equivalence scoring, rollback,
  deployment, remote support agents, or managed environment mutation.
- Universal physical setup ontology, universal parameter schema, or full
  hardware-resource arbitration.
- Treating a software snapshot as enough proof of scientific comparability.

## Possible Validation Questions

- Can users decide what changed, what is missing, and what still needs manual
  checking from a known-good comparison without Scopecat claiming setup truth?
- Which diagnostic facts are safe and useful for internal support, and which
  must be omitted or redacted for public/exported artifacts?
