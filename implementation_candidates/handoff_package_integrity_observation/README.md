# Handoff Package Integrity Observation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, a trust model, final package format, archive verifier, external
authenticity workflow, or import API.

It tests a read-only receiving-side check for directory-shaped handoff
packages:

- read `package-manifest.json` from an existing package directory;
- validate the manifest through the existing handoff package contents-preview
  contract;
- require the directory name to match the manifest package id;
- collect manifest-declared packaged members with package-relative paths;
- read package-local regular files without following symlink targets or
  symlink parents;
- calculate observed sha256 and byte size for available members;
- compare observed facts against declared digest and size where both are
  present;
- report verified, mismatched, unavailable, blocked, or not-declared member
  states as local review facts.

The slice intentionally stays narrower than package acceptance. It does not
mutate storage, import records, extract archives, validate external authenticity, infer
schemas, load CSV tables, render GUI output, support adversarial concurrent
package mutation, or promote checksum comparison into a complete package
integrity or authenticity guarantee.
