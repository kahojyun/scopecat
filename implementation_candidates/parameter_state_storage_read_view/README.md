# Parameter State Storage Read View Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a read-only view over one explicitly referenced stored parameter-state
manifest and write receipt:

- read only declared manifest and receipt paths under a caller-provided
  storage root;
- validate sha256 and size facts for both files;
- validate receipt-to-manifest continuity and state identity;
- expose parameter-state summary, trusted entries, provenance, and excluded
  preview entries;
- keep catalog discovery, storage mutation, legacy source observation, schema
  migration, external file authority, hardware write-back, GUI behavior, and
  shared domain models out of scope.

The package exists to test consumption of stored parameter state without
depending on writer internals or final storage architecture.
