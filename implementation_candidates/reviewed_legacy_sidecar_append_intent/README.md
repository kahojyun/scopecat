# Reviewed Legacy Sidecar Append Intent Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow intent boundary:

- consume a prior legacy locator-observation review bundle;
- require explicit local reviewer approval;
- select reviewed sidecar and locator-observation facts for later append as
  review/debug evidence;
- keep primary data, legacy payloads, reference repair, and validity state out
  of the append intent.

The candidate intentionally does not write storage, append records, import
primary data, parse legacy data, repair references, write parameters, decide
measurement validity, or define GUI behavior.
