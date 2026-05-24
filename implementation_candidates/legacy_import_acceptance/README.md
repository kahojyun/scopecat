# Legacy Import Acceptance Candidate

This package is an implementation candidate, not accepted Scopecat
architecture or a stable import API.

The candidate tests the first review-to-acceptance boundary for normalized
adapter-authored legacy import manifests. It starts after a user-owned adapter
has emitted a public-safe manifest and an import review has approved accepting
that manifest into Scopecat-managed measurement storage.

The candidate:

- validates the embedded adapter-authored manifest with the existing manifest
  summary candidate;
- requires an explicit approved acceptance request;
- copies one declared primary-data file into a new record directory under a
  caller-provided storage root after sha256 and size preflight;
- writes a deterministic imported-record manifest that preserves adapter,
  external source identity, preview metadata, and linked-context references;
- refuses existing targets and symlink parents.

It deliberately does not parse legacy formats, define a stable public adapter
API, accept Scopecat export packages, infer schemas, traverse relations,
import linked context payloads, merge or update existing records, validate
package integrity, or define GUI behavior.
