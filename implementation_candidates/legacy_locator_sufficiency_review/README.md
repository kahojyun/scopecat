# Legacy Locator Sufficiency Review Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow review-only boundary for legacy locator declarations:

- consume a legacy-run sidecar manifest summary;
- review whether declared legacy locators are sufficient for a user to find
  data in the old system;
- keep locators backend-specific and opaque;
- avoid parsing IDs, opening paths, connecting to legacy services, importing
  records, repairing references, or writing storage.

The candidate tests the same posture as reference-only legacy import: Scopecat
may preserve declared external references and surface review findings without
becoming responsible for one legacy system's reference scheme.
