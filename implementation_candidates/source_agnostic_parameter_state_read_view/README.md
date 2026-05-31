# Source-Agnostic Parameter-State Read View Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow read-only surface over explicit stored parameter-state
references:

- read declared manifest and receipt files only;
- support adapter-derived and calibration-derived stored parameter states;
- project common state, entry, digest, size, and receipt-continuity facts;
- preserve adapter and calibration provenance as typed provenance payloads;
- avoid catalog discovery, storage mutation, compatibility output, hardware
  write-back, schema migration, GUI behavior, and shared parameter schema
  extraction.

The package exists to test whether persisted parameter states can share a
common consumption surface without forcing different provenance families into
one schema.
