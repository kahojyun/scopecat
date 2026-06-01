# Supporting Artifact Provenance Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow provenance/source-link summary for supporting evidence that
is explicitly labeled as an artifact:

- consume one prior supporting-evidence reference summary;
- require the supporting evidence kind to be `artifact`;
- validate explicit direct producer and source links for that artifact;
- preserve source roles, source states, and review findings;
- avoid artifact or source payload import, file observation, checksum
  validation, storage mutation, artifact generation, recursive traversal,
  analysis-DAG inference, fit validation, measurement-validity decisions,
  GUI behavior, portable/public export, or shared artifact schema extraction.
