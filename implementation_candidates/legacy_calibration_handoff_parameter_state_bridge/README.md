# Legacy Calibration Handoff Parameter-State Bridge Candidate

This candidate composes:

```text
legacy brownfield adoption backbone
-> calibration accepted-write handoff
-> calibration parameter-state intake summary
```

It validates that a post-run legacy sidecar can carry a reviewed calibration
handoff into parameter-state management without making Scopecat write legacy
parameter files, control hardware, import primary data, or execute calibration.

The bridge is explicit. It does not infer calibration handoffs from legacy file
names, notebook state, debug artifacts, or primary-data payloads.
