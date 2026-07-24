export interface ConfigSnapshotSummary {
  id: string;
  labId?: string;
  primaryEntityId?: string;
  parameterCount: number;
  instrumentCount: number;
  connectionCount: number;
}

export interface ConfigRegistrySource {
  kind: string;
  runId?: string;
  proposalIds: string[];
}

export interface ConfigRegistryEntry {
  id: string;
  contentHash: string;
  configRef?: string;
  registeredBy?: string;
  registeredAt?: string;
  note?: string;
  source: ConfigRegistrySource;
  snapshot?: ConfigSnapshotSummary;
}

export interface ConfigActivationRecord {
  id: string;
  generation: number;
  action: "activation" | "rollback";
  entryId: string;
  entryContentHash: string;
  previousEntryId?: string;
  operator?: string;
  note?: string;
  recordedAt?: string;
}

export interface ActiveConfigState {
  generation: number;
  entryId: string;
  contentHash: string;
  updatedAt?: string;
  snapshot?: ConfigSnapshotSummary;
}

export interface ConfigRegistryOverview {
  active?: ActiveConfigState;
  entries: ConfigRegistryEntry[];
  history: ConfigActivationRecord[];
}

export interface ConfigRegistryEntryDetail {
  entry: ConfigRegistryEntry;
  snapshot: ConfigSnapshotSummary;
}

export interface ConfigCommand {
  operator: string;
  note?: string;
  expectedGeneration: number;
}

export interface ImportConfigCommand {
  entryId: string;
  registeredBy: string;
  note?: string;
  config: Record<string, unknown>;
}
