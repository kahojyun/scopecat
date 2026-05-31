# Adapter-Authored Parameter Compatibility Output Preview Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests the adapter-to-Scopecat return boundary for compatibility output:

- consume one approved parameter compatibility adapter request summary;
- validate one adapter-authored compatibility output manifest/receipt;
- require request, approval, prepared-run context, measurement, parameter-state,
  adapter, target, and entry continuity;
- preserve adapter-declared output identity, target display, digest/size facts,
  emitted/skipped entries, and adapter findings;
- avoid Scopecat parsing of the lab-specific output, file writes, file
  observation, hardware control, parameter write-back, external file authority,
  durable storage, GUI behavior, managed runner behavior, and stable public
  adapter API extraction.
