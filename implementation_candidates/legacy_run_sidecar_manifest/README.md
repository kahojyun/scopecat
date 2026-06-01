# Legacy Run Sidecar Manifest Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow brownfield adoption boundary:

- old experiment scripts, notebooks, runners, and legacy storage keep
  executing outside Scopecat;
- Scopecat records a declared sidecar manifest around that run;
- selected run-start context remains optional and reference-only;
- legacy primary data and supporting evidence are declared references, not file
  reads or imports;
- missing context and unavailable references become local review findings.

The package deliberately avoids hardware control, notebook execution, legacy
adapter import, primary-data observation, parameter write-back, storage
mutation, schema inference, GUI behavior, and any claim that sidecar review
findings block or validate the run.
