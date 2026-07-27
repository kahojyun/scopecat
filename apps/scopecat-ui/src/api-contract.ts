import type { components, paths } from "./api-schema";

type JsonResponse<Operation, Status extends PropertyKey> = Operation extends {
  responses: infer Responses;
}
  ? Status extends keyof Responses
    ? Responses[Status] extends {
        content: { "application/json": infer Payload };
      }
      ? Payload
      : never
    : never
  : never;

type JsonRequest<Operation> = Operation extends {
  requestBody: {
    content: { "application/json": infer Payload };
  };
}
  ? Payload
  : never;

export interface DaemonUiApi {
  health: JsonResponse<paths["/api/v1/health"]["get"], 200>;
  configRegistry: JsonResponse<paths["/api/v1/config-registry"]["get"], 200>;
  configActivations: JsonResponse<paths["/api/v1/config-registry/activations"]["get"], 200>;
  activeConfig: JsonResponse<paths["/api/v1/config-registry/active"]["get"], 200>;
  configEntry: JsonResponse<paths["/api/v1/config-registry/entries/{entry_id}"]["get"], 200>;
  configPublishReceipt: JsonResponse<paths["/api/v1/config-registry/default"]["post"], 200>;
  configDraftPreview: JsonResponse<paths["/api/v1/config-registry/drafts/preview"]["post"], 200>;
  configActivationReceipt: JsonResponse<paths["/api/v1/config-registry/active"]["post"], 200>;
  configUndoReceipt: JsonResponse<paths["/api/v1/config-registry/undo"]["post"], 200>;
  runPage: JsonResponse<paths["/api/v1/runs"]["get"], 200>;
  runDetail: JsonResponse<paths["/api/v1/runs/{run_id}"]["get"], 200>;
  runAnalyses: JsonResponse<paths["/api/v1/runs/{run_id}/analyses"]["get"], 200>;
  parameterProposals: JsonResponse<paths["/api/v1/runs/{run_id}/parameter-proposals"]["get"], 200>;
  artifactText: JsonResponse<paths["/api/v1/runs/{run_id}/artifacts/{selector}/text"]["get"], 200>;
  artifactJson: JsonResponse<paths["/api/v1/runs/{run_id}/artifacts/{selector}/json"]["get"], 200>;
  recordJson: JsonResponse<paths["/api/v1/runs/{run_id}/records/{selector}/json"]["get"], 200>;
  datasetContent: JsonResponse<paths["/api/v1/runs/{run_id}/datasets/{selector}"]["get"], 200>;
  measurements: JsonResponse<paths["/api/v1/runs/{run_id}/measurements"]["get"], 200>;
  eventPage: JsonResponse<paths["/api/v1/events"]["get"], 200>;
  instrumentList: JsonResponse<paths["/api/v1/instruments"]["get"], 200>;
  instrument: JsonResponse<paths["/api/v1/instruments/{instrument_id}"]["get"], 200>;
  instrumentSessionLease: JsonResponse<paths["/api/v1/instrument-sessions"]["post"], 201>;
  instrumentHeartbeatLease: JsonResponse<
    paths["/api/v1/instrument-sessions/{session_id}/heartbeat"]["post"],
    200
  >;
  instrumentState: JsonResponse<
    paths["/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/state/read"]["post"],
    200
  >;
  instrumentApplyReceipt: JsonResponse<
    paths["/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/state/apply"]["post"],
    200
  >;
  instrumentCollectReceipt: JsonResponse<
    paths["/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/collect"]["post"],
    200
  >;
  instrumentSessionEndReceipt: JsonResponse<
    paths["/api/v1/instrument-sessions/{session_id}/close"]["post"],
    200
  >;
  configPublishCommand: JsonRequest<paths["/api/v1/config-registry/default"]["post"]>;
  configDraftCommand: JsonRequest<paths["/api/v1/config-registry/drafts/preview"]["post"]>;
  configActivationCommand: JsonRequest<paths["/api/v1/config-registry/active"]["post"]>;
  configUndoCommand: JsonRequest<paths["/api/v1/config-registry/undo"]["post"]>;
  instrumentSessionOpenCommand: JsonRequest<paths["/api/v1/instrument-sessions"]["post"]>;
  instrumentHeartbeatCommand: JsonRequest<
    paths["/api/v1/instrument-sessions/{session_id}/heartbeat"]["post"]
  >;
  instrumentReadCommand: JsonRequest<
    paths["/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/state/read"]["post"]
  >;
  instrumentApplyCommand: JsonRequest<
    paths["/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/state/apply"]["post"]
  >;
  instrumentCollectCommand: JsonRequest<
    paths["/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/collect"]["post"]
  >;
  instrumentSessionEndCommand: JsonRequest<
    paths["/api/v1/instrument-sessions/{session_id}/close"]["post"]
  >;
}

export type ControlRun = components["schemas"]["ControlRun"];
export type ConfigActivationRecord = components["schemas"]["ConfigRegistryActivationRecord"];
export type ConfigDraftCommand = DaemonUiApi["configDraftCommand"];
export type ConfigPublishCommand = DaemonUiApi["configPublishCommand"];
export type ConfigPublishReceipt = Omit<DaemonUiApi["configPublishReceipt"], "deltas"> & {
  deltas: ParameterValueDelta[];
};
export type ConfigDraftPreview = Omit<DaemonUiApi["configDraftPreview"], "config" | "deltas"> & {
  config?: ConfigProfileSnapshot | null;
  deltas: ParameterValueDelta[];
};
export type ConfigProfileSnapshot = components["schemas"]["ConfigProfileSnapshot-Input"];
export type ConfigRegistryEntry = components["schemas"]["ConfigRegistryEntry"];
export type ConfigRegistryOverview = DaemonUiApi["configRegistry"] & {
  activation_history: ConfigActivationRecord[];
};
export type DurableEvent = components["schemas"]["DurableEvent"];
export type EntityRef = components["schemas"]["EntityRef-Input"];
export type ExternalLocation = components["schemas"]["ExternalLocation"];
export type InstrumentApplyReceipt = DaemonUiApi["instrumentApplyReceipt"];
export type InstrumentCapability = components["schemas"]["CapabilityDescription"];
export type InstrumentCapabilityField = components["schemas"]["CapabilityField"];
export type InstrumentCollectReceipt = DaemonUiApi["instrumentCollectReceipt"];
export type InstrumentConnection = components["schemas"]["InstrumentConnection-Input"];
export type InstrumentDescription = components["schemas"]["InstrumentDescription"];
export type InstrumentSessionLease = DaemonUiApi["instrumentSessionLease"];
export type InstrumentSpec = components["schemas"]["InstrumentSpec-Input"];
export type InstrumentState = DaemonUiApi["instrumentState"];
export type InstrumentStateValue = components["schemas"]["StateValue"];
export type InstrumentView = DaemonUiApi["instrument"];
export type ParameterAtom = components["schemas"]["ParameterAtomValue-Input"];
export type ParameterDefinition = components["schemas"]["ParameterDefinition"];
export type ParameterEntity = components["schemas"]["EntityRef-Input"];
export type ParameterUpdate = components["schemas"]["ParameterUpdate"];
export type ParameterQuantity = components["schemas"]["scopecat__kernel__quantity__Quantity"];
export type ParameterScalarType =
  | Extract<components["schemas"]["PersistableValueType"], { shape: "scalar" }>["atom"]
  | Extract<
      components["schemas"]["PersistableValueType"],
      { shape: "table" }
    >["columns"][number]["value_type"];
export type ParameterValueDelta = Omit<
  components["schemas"]["ParameterValueDelta-Output"],
  "before" | "after"
> & {
  before: StoredParameterValue;
  after: StoredParameterValue;
};
export type ParameterValueType = components["schemas"]["PersistableValueType"];
export type Quantity = components["schemas"]["scopecat__kernel__quantity__Quantity"];
export type RunContentEntry = components["schemas"]["RunContentEntry-Output"];
export type RunManifest = components["schemas"]["RunManifest"];
export type RunResourceView = components["schemas"]["RunResourceView"];
export type StoredParameterValue = components["schemas"]["StoredParameterValue-Input"];
export type TableParameterType = Extract<ParameterValueType, { shape: "table" }>;
export type TableParameterValue = Extract<StoredParameterValue, { shape: "table" }>;
