# Prepared Run Approval View State Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests a read-only view-state projection over the prepared-run
parameter-state review and approval path:

- consume one operator pre-run approval summary;
- present the selected parameter-state snapshot as the canonical parameter
  context;
- surface partial target-coverage acknowledgement and operator decision state;
- expose remaining findings and labels-only review actions;
- omit compatibility artifacts unless they are explicitly supplied later as
  debug attachments;
- avoid GUI framework commitments, action execution, run start, hardware
  control, parameter write-back, compatibility output, fresh reads, durable
  storage, environment operation, code execution, managed runner behavior, and
  shared view schema extraction.
