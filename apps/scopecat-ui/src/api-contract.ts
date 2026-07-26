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
  configEntry: JsonResponse<paths["/api/v1/config-registry/entries/{entry_id}"]["get"], 200>;
  configImportedEntry: JsonResponse<paths["/api/v1/config-registry/entries"]["post"], 201>;
  configDraftPreview: JsonResponse<paths["/api/v1/config-registry/drafts/preview"]["post"], 200>;
  configDraftRegistrationReceipt: JsonResponse<
    paths["/api/v1/config-registry/drafts/register"]["post"],
    201
  >;
  configDraftDefaultReceipt: JsonResponse<
    paths["/api/v1/config-registry/drafts/set-default"]["post"],
    200
  >;
  configActivationReceipt: JsonResponse<paths["/api/v1/config-registry/active"]["post"], 200>;
  configRollbackReceipt: JsonResponse<paths["/api/v1/config-registry/rollback"]["post"], 200>;
  candidateConfigActivationReceipt: JsonResponse<
    paths["/api/v1/config-registry/candidates/activate"]["post"],
    200
  >;
  runPage: JsonResponse<paths["/api/v1/runs"]["get"], 200>;
  runDetail: JsonResponse<paths["/api/v1/runs/{run_id}"]["get"], 200>;
  runAnalyses: JsonResponse<paths["/api/v1/runs/{run_id}/analyses"]["get"], 200>;
  parameterProposals: JsonResponse<paths["/api/v1/runs/{run_id}/parameter-proposals"]["get"], 200>;
  parameterProposalDecision: JsonResponse<
    paths["/api/v1/runs/{run_id}/parameter-proposals/{proposal_id}/decision"]["post"],
    200
  >;
  artifactText: JsonResponse<paths["/api/v1/runs/{run_id}/artifacts/{selector}/text"]["get"], 200>;
  artifactJson: JsonResponse<paths["/api/v1/runs/{run_id}/artifacts/{selector}/json"]["get"], 200>;
  recordJson: JsonResponse<paths["/api/v1/runs/{run_id}/records/{selector}/json"]["get"], 200>;
  datasetContent: JsonResponse<paths["/api/v1/runs/{run_id}/datasets/{selector}"]["get"], 200>;
  measurements: JsonResponse<paths["/api/v1/runs/{run_id}/measurements"]["get"], 200>;
  eventPage: JsonResponse<paths["/api/v1/events"]["get"], 200>;
  configImportCommand: JsonRequest<paths["/api/v1/config-registry/entries"]["post"]>;
  configDraftCommand: JsonRequest<paths["/api/v1/config-registry/drafts/preview"]["post"]>;
  configDraftRegistrationCommand: JsonRequest<
    paths["/api/v1/config-registry/drafts/register"]["post"]
  >;
  configDraftDefaultCommand: JsonRequest<
    paths["/api/v1/config-registry/drafts/set-default"]["post"]
  >;
  configActivationCommand: JsonRequest<paths["/api/v1/config-registry/active"]["post"]>;
  configRollbackCommand: JsonRequest<paths["/api/v1/config-registry/rollback"]["post"]>;
  candidateConfigActivationCommand: JsonRequest<
    paths["/api/v1/config-registry/candidates/activate"]["post"]
  >;
  parameterProposalDecisionCommand: JsonRequest<
    paths["/api/v1/runs/{run_id}/parameter-proposals/{proposal_id}/decision"]["post"]
  >;
}

export type ControlRun = components["schemas"]["ControlRun"];
export type ConfigActivationRecord = components["schemas"]["ConfigRegistryActivationRecord"];
export type ConfigDraftCommand = DaemonUiApi["configDraftCommand"];
export type ConfigDraftDefaultCommand = DaemonUiApi["configDraftDefaultCommand"];
export type ConfigDraftDefaultReceipt = Omit<DaemonUiApi["configDraftDefaultReceipt"], "deltas"> & {
  deltas: ParameterValueDelta[];
};
export type ConfigDraftPreview = Omit<DaemonUiApi["configDraftPreview"], "config" | "deltas"> & {
  config?: ConfigProfileSnapshot | null;
  deltas: ParameterValueDelta[];
};
export type ConfigDraftRegistrationCommand = DaemonUiApi["configDraftRegistrationCommand"];
export type ConfigDraftRegistrationReceipt = Omit<
  DaemonUiApi["configDraftRegistrationReceipt"],
  "deltas"
> & {
  deltas: ParameterValueDelta[];
};
export type ConfigProfileSnapshot = components["schemas"]["ConfigProfileSnapshot-Input"];
export type ConfigRegistryActiveState = components["schemas"]["ConfigRegistryActiveState"];
export type ConfigRegistryEntry = components["schemas"]["ConfigRegistryEntry"];
export type ConfigRegistryOverview = DaemonUiApi["configRegistry"];
export type DurableEvent = components["schemas"]["DurableEvent"];
export type EntityRef = components["schemas"]["EntityRef-Input"];
export type ExternalLocation = components["schemas"]["ExternalLocation"];
export type ParameterAtom = components["schemas"]["ParameterAtomValue-Input"];
export type ParameterDefinition = components["schemas"]["ParameterDefinition"];
export type ParameterEntity = components["schemas"]["EntityRef-Input"];
export type ParameterUpdate = components["schemas"]["ParameterUpdate"];
export type ParameterQuantity = components["schemas"]["scopecat__kernel__quantity__Quantity"];
export type ParameterScalarType =
  | Extract<components["schemas"]["PersistableValueType"], { shape: "scalar" }>["atom"]
  | Extract<components["schemas"]["PersistableValueType"], { shape: "series" }>["item_type"]
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
export type SeriesParameterValue = Extract<StoredParameterValue, { shape: "series" }>;
export type StoredParameterValue = components["schemas"]["StoredParameterValue-Input"];
export type TableParameterType = Extract<ParameterValueType, { shape: "table" }>;
export type TableParameterValue = Extract<StoredParameterValue, { shape: "table" }>;
