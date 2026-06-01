# Legacy Brownfield Adoption Backbone Candidate

This candidate composes existing legacy-sidecar review candidates into one
post-run-first adoption backbone:

```text
legacy sidecar summary
-> post-run review
-> locator-observation review bundle
-> approved append intent
-> review-evidence receipt write summary
-> receipt read view
```

It validates identity continuity and boundary posture across prior summaries.
It does not execute legacy code, observe files, write storage, import primary
data, parse payloads, repair references, write parameters, decide measurement
validity, define GUI behavior, or create a final workflow schema.

The fixture posture is intentionally post-run first. The legacy sidecar events
are declared batch facts, so the same lifecycle vocabulary can later be emitted
during a run without making this candidate a runner hook or live sidecar
writer.
