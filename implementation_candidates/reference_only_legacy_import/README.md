# Reference-Only Legacy Import Candidate

This package is an implementation candidate, not accepted Scopecat
architecture or a stable import API.

The candidate tests the reference-only side of legacy import acceptance for
lab-managed shared storage. A user-owned adapter has already emitted a
normalized adapter-authored manifest, and review has approved preserving the
legacy source location as a current external reference instead of copying
primary data into Scopecat storage.

The candidate:

- validates the embedded adapter-authored manifest with the existing manifest
  summary candidate;
- requires an explicit approved reference-only acceptance request;
- validates public-safe lab-managed current-reference display facts;
- preserves adapter identity, external source identity, declared preview
  metadata, and linked-context references;
- reports source openability, digest, size, and schema verification as
  unobserved.

It deliberately does not parse legacy formats, copy primary data, write
storage, define a stable public adapter API, accept Scopecat export packages,
infer schemas, traverse relations, import linked-context payloads, repair
external references, or define GUI behavior.
