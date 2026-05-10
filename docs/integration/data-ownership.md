# Data Ownership

## Status

Draft ownership map.

## Rule

Every durable concept should have one owning subsystem. Other subsystems may
reference it but should not redefine it.

## Current Ownership Map

| Concept | Owner |
| --- | --- |
| ExperimentRun | Measurement History |
| Dataset | Measurement History |
| DerivedDataset | Measurement History |
| ScanPointRecord | Measurement History |
| ScanPlan | Scan Framework |
| ScanVariable | Scan Framework |
| DesiredInstrumentState | Scan Framework |
| ActualInstrumentState | Instrument Runtime |
| ParameterSnapshot | Parameter Memory |
| ParameterUpdateProposal | Parameter Memory |
| CodeAsset | Code Asset Registry |
| CodeVersion | Code Asset Registry |
| CodeEntrypoint | Code Asset Registry |
| Instrument | Instrument Runtime |
| LabResource | Instrument Runtime |
| ResourceLease | Instrument Runtime |
| InstrumentService | Instrument Runtime |
| ExecutionRecord | Managed Code Runner |
| EnvironmentSnapshot | Managed Code Runner |
| Artifact | Managed Code Runner |
| WorkflowRun | Workflow / Orchestration |
| ExperimentPackage | Remote Execution / Integration Contract |

## Open Questions

- Should `Artifact` be owned by Managed Code Runner, Measurement History, or
  split by artifact kind?
- Should `ExperimentPackage` have a dedicated owning subsystem later, or remain
  an integration contract?
