# Legacy Sidecar Post-Run Review Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow post-run review projection for legacy sidecar workflows:

- consume a legacy-run sidecar manifest summary;
- consume a legacy locator sufficiency review summary for the same sidecar;
- present sidecar lifecycle, locator review, primary data references, and
  supporting evidence references together;
- avoid fresh observation, import, storage mutation, reference repair,
  parameter write-back, or GUI behavior.

The candidate is intentionally a local review surface. It does not make
sidecar facts durable measurement-record updates or decide measurement
validity.
