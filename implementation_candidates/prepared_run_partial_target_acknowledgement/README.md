# Prepared Run Partial Target Acknowledgement Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a narrow local review decision over a known prepared-run scope
finding:

- consume a source-agnostic parameter-state review-chain summary;
- require an explicit user acknowledgement of the exact partial target
  coverage finding;
- preserve the original finding basis and user review note;
- expose remaining review findings after acknowledgement;
- avoid parameter invalidation, parameter write-back, compatibility output,
  hardware control, scope repair, setup mutation, fresh storage reads, catalog
  discovery, automatic run start, GUI behavior, and shared acknowledgement
  schema extraction.
