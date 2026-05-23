# Measurement Record Import Preview Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first measurement-record
import preview slice:

- build a structured summary from an explicit incoming-record manifest;
- keep the builder side-effect free;
- classify incoming records for preview review without accepting or importing
  them;
- preserve declared source identity, current-reference state, primary-data
  references, preview metadata, and linked-context references;
- report unavailable source data, missing preview metadata, and unavailable
  linked context as review findings;
- avoid source-file reads, source observation, storage mutation, importer
  behavior, package acceptance, checksum contracts, schema inference, recursive
  relation traversal, GUI behavior, or shared measurement schema.

The package exists to test whether Scopecat can preview and classify incoming
measurement records before any import or storage authority is accepted.
