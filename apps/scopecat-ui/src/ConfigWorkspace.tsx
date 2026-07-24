import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  Database,
  FileUp,
  GitCompareArrows,
  History,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  UserRound,
  X,
  XCircle,
} from "lucide-react";
import { ApiError } from "./api";
import {
  activateConfigEntry,
  getConfigRegistry,
  getConfigRegistryEntry,
  importConfigProfile,
  parseConfigProfileJson,
  rollbackConfig,
} from "./config-api";
import type {
  ConfigActivationRecord,
  ConfigRegistryEntry,
  ConfigRegistryOverview,
  ConfigSnapshotSummary,
} from "./config-types";

type ConfigMutation =
  | { kind: "activate-entry"; entryId: string }
  | { kind: "rollback" }
  | { kind: "import"; draft: ImportDraft };

interface ImportDraft {
  fileName: string;
  entryId: string;
  config: Record<string, unknown>;
}

export function ConfigWorkspace({
  daemonUnavailable,
}: {
  daemonUnavailable: boolean;
}) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [selectedId, setSelectedId] = useState<string>();
  const [registrySearch, setRegistrySearch] = useState("");
  const [operator, setOperator] = useState("local-operator");
  const [note, setNote] = useState("");
  const [importDraft, setImportDraft] = useState<ImportDraft>();
  const [importError, setImportError] = useState<string>();

  const registryQuery = useQuery({
    queryKey: ["config", "registry"],
    queryFn: ({ signal }) => getConfigRegistry(signal),
    enabled: !daemonUnavailable,
    refetchInterval: 5_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
  });
  const overview = registryQuery.data;
  const generation = overview?.active?.generation ?? 0;

  const mutation = useMutation({
    mutationFn: async (action: ConfigMutation) => {
      const command = {
        operator: operator.trim(),
        note: note.trim(),
        expectedGeneration: generation,
      };
      if (!command.operator) {
        throw new Error("Enter an operator name before changing configuration.");
      }
      switch (action.kind) {
        case "activate-entry":
          await activateConfigEntry(action.entryId, command);
          return;
        case "rollback":
          await rollbackConfig(command);
          return;
        case "import":
          await importConfigProfile({
            entryId: action.draft.entryId,
            registeredBy: command.operator,
            note: command.note,
            config: action.draft.config,
          });
      }
    },
    onSuccess: async (_, action) => {
      if (action.kind === "import") setImportDraft(undefined);
      setNote("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["config"] }),
        queryClient.invalidateQueries({ queryKey: ["events"] }),
      ]);
    },
  });

  useEffect(() => {
    if (!overview) return;
    const selectionExists = overview.entries.some(
      (entry) => entry.id === selectedId,
    );
    if (selectionExists) return;
    const preferred =
      overview.entries.find(
        (entry) => entry.id === overview.active?.entryId,
      ) ?? overview.entries[0];
    if (preferred) {
      setSelectedId(preferred.id);
    }
  }, [overview, selectedId]);

  const filteredEntries = useMemo(
    () => filterEntries(overview?.entries ?? [], registrySearch),
    [overview?.entries, registrySearch],
  );
  const selectedEntry = overview?.entries.find(
    (entry) => entry.id === selectedId,
  );
  const entryDetailQuery = useQuery({
    queryKey: ["config", "entry", selectedEntry?.id],
    queryFn: ({ signal }) => getConfigRegistryEntry(selectedEntry!.id, signal),
    enabled:
      selectedEntry !== undefined &&
      selectedEntry.id !== overview?.active?.entryId,
  });
  const commandDisabled =
    mutation.isPending || !operator.trim();

  const selectEntry = (entryId: string) => {
    setSelectedId(entryId);
    mutation.reset();
  };
  const runAction = (action: ConfigMutation, confirmation: string) => {
    if (!window.confirm(confirmation)) return;
    mutation.mutate(action);
  };
  const readImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setImportError(undefined);
    try {
      const config = parseConfigProfileJson(await file.text());
      setImportDraft({
        fileName: file.name,
        entryId: safeEntryId(
          String(config.id ?? file.name.replace(/\.[^.]+$/, "")),
        ),
        config,
      });
    } catch (error) {
      setImportError(errorMessage(error));
    }
  };

  if (daemonUnavailable) {
    return (
      <ConfigBoundaryMessage
        icon={<Database />}
        title="Connect to the local daemon"
        detail="Configuration is owned by the daemon. This console does not keep an editable browser copy."
      />
    );
  }
  if (registryQuery.isPending) {
    return (
      <ConfigBoundaryMessage
        icon={<LoaderCircle className="spin" />}
        title="Reading configuration registry"
        detail="Loading the active snapshot, registered entries, and activation history."
      />
    );
  }
  if (registryQuery.isError) {
    return (
      <ConfigBoundaryMessage
        icon={<XCircle />}
        title="Configuration registry unavailable"
        detail={errorMessage(registryQuery.error)}
        warning
        action={
          <button
            className="secondary-button"
            type="button"
            onClick={() => void registryQuery.refetch()}
          >
            <RefreshCw size={15} aria-hidden="true" />
            Retry
          </button>
        }
      />
    );
  }
  if (!overview) {
    return (
      <ConfigBoundaryMessage
        icon={<XCircle />}
        title="Configuration registry unavailable"
        detail="The daemon returned no registry projection."
        warning
      />
    );
  }

  return (
    <section className="config-workspace" aria-labelledby="config-heading">
      <header className="config-toolbar">
        <div>
          <p className="eyebrow">Configuration registry</p>
          <h2 id="config-heading">Lab configuration</h2>
          <p>
            Review immutable snapshots and make one generation-checked change at
            a time.
          </p>
        </div>
        <div className="config-toolbar-actions">
          <label className="operator-field">
            <UserRound size={15} aria-hidden="true" />
            <span className="visually-hidden">Operator name</span>
            <input
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
              placeholder="Operator"
              autoComplete="name"
            />
          </label>
          <input
            ref={fileInput}
            className="visually-hidden"
            type="file"
            accept=".json,application/json"
            onChange={(event) => void readImport(event)}
          />
          <button
            className="primary-button"
            type="button"
            onClick={() => fileInput.current?.click()}
          >
            <FileUp size={15} aria-hidden="true" />
            Import snapshot
          </button>
        </div>
      </header>

      {(importError || mutation.error) && (
        <div className="config-error" role="status">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>{importError ?? errorMessage(mutation.error)}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => {
              setImportError(undefined);
              mutation.reset();
            }}
          >
            <X size={15} />
          </button>
        </div>
      )}

      <ConfigSummary
        overview={overview}
        rollbackDisabled={
          commandDisabled ||
          overview.history.length < 2 ||
          overview.active === undefined
        }
        rollbackPending={
          mutation.isPending && mutation.variables?.kind === "rollback"
        }
        onRollback={() =>
          runAction(
            { kind: "rollback" },
            `Roll back generation ${generation} to its previous registered configuration?`,
          )
        }
      />

      <div className="config-layout">
        <aside className="config-registry-panel" aria-label="Config registry">
          <div className="config-panel-heading">
            <div>
              <span>Registry</span>
              <strong>{overview.entries.length} entries</strong>
            </div>
            {registryQuery.isFetching && (
              <LoaderCircle
                className="spin"
                size={16}
                aria-label="Refreshing configuration"
              />
            )}
          </div>
          <label className="config-search">
            <Search size={15} aria-hidden="true" />
            <span className="visually-hidden">Search registry entries</span>
            <input
              type="search"
              placeholder="Find entry"
              value={registrySearch}
              onChange={(event) => setRegistrySearch(event.target.value)}
            />
          </label>
          <div className="config-entry-list">
            {overview.entries.length === 0 ? (
              <ConfigInlineEmpty
                title="Registry is empty"
                detail="Import a validated config snapshot to create the first entry."
              />
            ) : filteredEntries.length === 0 ? (
              <ConfigInlineEmpty
                title="No matching entries"
                detail="Try another id, operator, source run, or note."
              />
            ) : (
              filteredEntries.map((entry) => (
                <RegistryEntryButton
                  key={entry.id}
                  entry={entry}
                  active={entry.id === overview.active?.entryId}
                  selected={entry.id === selectedId}
                  onSelect={() => selectEntry(entry.id)}
                />
              ))
            )}
          </div>
        </aside>

        <section className="config-inspector" aria-live="polite">
          {selectedEntry ? (
            <EntryInspector
              entry={selectedEntry}
              active={overview.active?.entryId === selectedEntry.id}
              snapshot={
                overview.active?.entryId === selectedEntry.id
                  ? overview.active.snapshot
                  : entryDetailQuery.data?.snapshot
              }
              snapshotPending={entryDetailQuery.isPending}
              snapshotError={entryDetailQuery.error}
              note={note}
              pending={
                mutation.isPending &&
                mutation.variables?.kind === "activate-entry"
              }
              actionDisabled={commandDisabled}
              onNoteChange={setNote}
              onActivate={() =>
                runAction(
                  { kind: "activate-entry", entryId: selectedEntry.id },
                  `Activate ${selectedEntry.id} as generation ${generation + 1}?`,
                )
              }
            />
          ) : (
            <ConfigBoundaryMessage
              icon={<CircleDot />}
              title="Nothing selected"
              detail="Choose a registered entry to inspect its immutable snapshot."
              compact
            />
          )}
        </section>
      </div>

      <ActivationHistory history={overview.history} />

      {importDraft && (
        <ImportDialog
          draft={importDraft}
          note={note}
          pending={
            mutation.isPending && mutation.variables?.kind === "import"
          }
          disabled={mutation.isPending || !operator.trim()}
          onChange={setImportDraft}
          onNoteChange={setNote}
          onCancel={() => setImportDraft(undefined)}
          onSubmit={() =>
            mutation.mutate({ kind: "import", draft: importDraft })
          }
        />
      )}
    </section>
  );
}

function ConfigSummary({
  overview,
  rollbackDisabled,
  rollbackPending,
  onRollback,
}: {
  overview: ConfigRegistryOverview;
  rollbackDisabled: boolean;
  rollbackPending: boolean;
  onRollback: () => void;
}) {
  return (
    <div className="config-summary-grid" aria-label="Configuration summary">
      <article className="active-config-card">
        <span className="config-summary-icon">
          <CheckCircle2 size={18} />
        </span>
        <div>
          <span>Active configuration</span>
          <strong>{overview.active?.entryId ?? "Not configured"}</strong>
          <code title={overview.active?.contentHash}>
            {overview.active
              ? shorten(overview.active.contentHash, 23)
              : "No active content hash"}
          </code>
        </div>
        <span className="generation-badge">
          Generation {overview.active?.generation ?? "—"}
        </span>
      </article>
      <ConfigMetric
        icon={<Database size={17} />}
        label="Registered"
        value={String(overview.entries.length)}
        detail="Immutable snapshots"
      />
      <ConfigMetric
        icon={<History size={17} />}
        label="Activations"
        value={String(overview.history.length)}
        detail="Durable generations"
      />
      <article className="rollback-card">
        <div>
          <span>Previous generation</span>
          <strong>
            {overview.history[1]?.entryId ?? "No rollback target"}
          </strong>
        </div>
        <button
          className="secondary-button"
          type="button"
          disabled={rollbackDisabled}
          onClick={onRollback}
        >
          {rollbackPending ? (
            <LoaderCircle className="spin" size={15} />
          ) : (
            <RotateCcw size={15} />
          )}
          Roll back
        </button>
      </article>
    </div>
  );
}

function ConfigMetric({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="config-metric">
      <span aria-hidden="true">{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>{detail}</p>
      </div>
    </article>
  );
}

function RegistryEntryButton({
  entry,
  active,
  selected,
  onSelect,
}: {
  entry: ConfigRegistryEntry;
  active: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={selected ? "config-entry selected" : "config-entry"}
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
    >
      <span className={active ? "entry-state active" : "entry-state"} />
      <span>
        <strong>{entry.id}</strong>
        <small>
          {sourceLabel(entry)}
          {entry.registeredAt ? ` · ${formatRelative(entry.registeredAt)}` : ""}
        </small>
        <code>{shorten(entry.contentHash, 22)}</code>
      </span>
      {active && <span className="active-label">Active</span>}
    </button>
  );
}

function EntryInspector({
  entry,
  active,
  snapshot,
  snapshotPending,
  snapshotError,
  note,
  pending,
  actionDisabled,
  onNoteChange,
  onActivate,
}: {
  entry: ConfigRegistryEntry;
  active: boolean;
  snapshot?: ConfigSnapshotSummary;
  snapshotPending: boolean;
  snapshotError: Error | null;
  note: string;
  pending: boolean;
  actionDisabled: boolean;
  onNoteChange: (note: string) => void;
  onActivate: () => void;
}) {
  const selectedSnapshot = entry.snapshot ?? snapshot;
  return (
    <>
      <header className="config-inspector-heading">
        <div>
          <span className={active ? "config-state active" : "config-state"}>
            {active ? "Active" : "Registered"}
          </span>
          <h3>{entry.id}</h3>
          <code title={entry.contentHash}>{entry.contentHash}</code>
        </div>
        {!active && (
          <button
            className="primary-button"
            type="button"
            disabled={actionDisabled}
            onClick={onActivate}
          >
            {pending ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <CheckCircle2 size={15} />
            )}
            Activate
          </button>
        )}
      </header>
      <div className="config-detail-facts">
        <ConfigFact label="Source" value={sourceLabel(entry)} />
        <ConfigFact
          label="Registered by"
          value={entry.registeredBy ?? "Not reported"}
        />
        <ConfigFact
          label="Registered"
          value={
            entry.registeredAt
              ? formatDateTime(entry.registeredAt)
              : "Not reported"
          }
        />
        <ConfigFact
          label="Config ref"
          value={entry.configRef ?? "Not reported"}
          code
        />
      </div>
      {entry.source.runId && (
        <div className="config-provenance">
          <GitCompareArrows size={16} aria-hidden="true" />
          <div>
            <strong>Candidate provenance</strong>
            <p>
              Resolved from run <code>{entry.source.runId}</code>
              {entry.source.proposalIds.length > 0
                ? ` using ${entry.source.proposalIds.length} approved proposals.`
                : "."}
            </p>
          </div>
        </div>
      )}
      {selectedSnapshot ? (
        <SnapshotSummary snapshot={selectedSnapshot} />
      ) : snapshotPending ? (
        <ConfigInlineEmpty
          title="Reading snapshot"
          detail="Loading this registry entry's immutable config snapshot."
        />
      ) : snapshotError ? (
        <ConfigInlineEmpty
          title="Snapshot unavailable"
          detail={errorMessage(snapshotError)}
        />
      ) : (
        <ConfigInlineEmpty
          title="Snapshot summary not included"
          detail="The registry projection can attach entry snapshots when detailed comparison is needed."
        />
      )}
      {entry.note && (
        <div className="config-entry-note">
          <span>Registration note</span>
          <p>{entry.note}</p>
        </div>
      )}
      {!active && (
        <ActionNote value={note} onChange={onNoteChange} />
      )}
    </>
  );
}

function SnapshotSummary({ snapshot }: { snapshot: ConfigSnapshotSummary }) {
  return (
    <section className="snapshot-summary" aria-label="Snapshot summary">
      <div className="snapshot-heading">
        <SlidersHorizontal size={17} aria-hidden="true" />
        <span>
          <strong>{snapshot.id}</strong>
          <small>{snapshot.labId ?? "Lab identity not reported"}</small>
        </span>
      </div>
      <div className="snapshot-metrics">
        <ConfigFact
          label="Parameters"
          value={String(snapshot.parameterCount)}
        />
        <ConfigFact
          label="Instruments"
          value={String(snapshot.instrumentCount)}
        />
        <ConfigFact
          label="Connections"
          value={String(snapshot.connectionCount)}
        />
        <ConfigFact
          label="Primary entity"
          value={snapshot.primaryEntityId ?? "Not reported"}
        />
      </div>
    </section>
  );
}

function ActivationHistory({
  history,
}: {
  history: ConfigActivationRecord[];
}) {
  return (
    <section className="activation-history" aria-labelledby="history-heading">
      <header>
        <span aria-hidden="true">
          <History size={17} />
        </span>
        <div>
          <h3 id="history-heading">Activation history</h3>
          <p>Every active pointer change is retained as a generation.</p>
        </div>
        <span className="history-count">{history.length}</span>
      </header>
      {history.length === 0 ? (
        <ConfigInlineEmpty
          title="No activation history"
          detail="The first activation will establish generation 1."
        />
      ) : (
        <ol>
          {history.map((record, index) => (
            <li key={record.id}>
              <span className="history-generation">
                <strong>G{record.generation}</strong>
                <small>{index === 0 ? "Current" : record.action}</small>
              </span>
              <span className="history-connector" aria-hidden="true" />
              <div>
                <strong>{record.entryId}</strong>
                <small>
                  {record.operator ?? "Unknown operator"}
                  {record.recordedAt
                    ? ` · ${formatDateTime(record.recordedAt)}`
                    : ""}
                </small>
                {record.note && <p>{record.note}</p>}
              </div>
              <code>{shorten(record.entryContentHash, 18)}</code>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ImportDialog({
  draft,
  note,
  pending,
  disabled,
  onChange,
  onNoteChange,
  onCancel,
  onSubmit,
}: {
  draft: ImportDraft;
  note: string;
  pending: boolean;
  disabled: boolean;
  onChange: (draft: ImportDraft) => void;
  onNoteChange: (note: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const validEntryId =
    draft.entryId.length > 0 && safeEntryId(draft.entryId) === draft.entryId;
  return (
    <div className="config-modal-backdrop">
      <section
        className="config-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-config-title"
      >
        <header>
          <span aria-hidden="true">
            <FileUp size={19} />
          </span>
          <div>
            <h3 id="import-config-title">Import config snapshot</h3>
            <p>{draft.fileName}</p>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onCancel}
            aria-label="Close import dialog"
          >
            <X size={16} />
          </button>
        </header>
        <div className="config-modal-body">
          <label>
            <span>Registry entry id</span>
            <input
              value={draft.entryId}
              onChange={(event) =>
                onChange({ ...draft, entryId: event.target.value })
              }
              aria-invalid={!validEntryId}
              autoFocus
            />
            {!validEntryId && (
              <small>
                Use letters, numbers, underscores, and hyphens; start with a
                letter or number.
              </small>
            )}
          </label>
          <ActionNote value={note} onChange={onNoteChange} />
        </div>
        <footer>
          <button
            className="secondary-button"
            type="button"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={disabled || !validEntryId}
            onClick={onSubmit}
          >
            {pending ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <FileUp size={15} />
            )}
            Import snapshot
          </button>
        </footer>
      </section>
    </div>
  );
}

function ActionNote({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="action-note">
      <span>Audit note</span>
      <textarea
        rows={2}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Why is this configuration changing?"
      />
    </label>
  );
}

function ConfigFact({
  label,
  value,
  code = false,
}: {
  label: string;
  value: string;
  code?: boolean;
}) {
  return (
    <div className="config-fact">
      <span>{label}</span>
      {code ? <code title={value}>{value}</code> : <strong>{value}</strong>}
    </div>
  );
}

function ConfigInlineEmpty({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="config-inline-empty">
      <CircleDot size={16} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
    </div>
  );
}

function ConfigBoundaryMessage({
  icon,
  title,
  detail,
  warning = false,
  compact = false,
  action,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  warning?: boolean;
  compact?: boolean;
  action?: ReactNode;
}) {
  return (
    <section
      className={`config-boundary${warning ? " warning" : ""}${
        compact ? " compact" : ""
      }`}
    >
      <span aria-hidden="true">{icon}</span>
      <h2>{title}</h2>
      <p>{detail}</p>
      {action}
    </section>
  );
}

function filterEntries(
  entries: ConfigRegistryEntry[],
  search: string,
): ConfigRegistryEntry[] {
  const query = search.trim().toLocaleLowerCase();
  if (!query) return entries;
  return entries.filter((entry) =>
    [
      entry.id,
      entry.registeredBy,
      entry.note,
      entry.source.kind,
      entry.source.runId,
      ...entry.source.proposalIds,
    ]
      .filter((value): value is string => value !== undefined)
      .join(" ")
      .toLocaleLowerCase()
      .includes(query),
  );
}

function sourceLabel(entry: ConfigRegistryEntry): string {
  return entry.source.kind === "candidate_config"
    ? "Candidate config"
    : "Direct profile";
}

function safeEntryId(value: string): string {
  const normalized = value
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return /^[A-Za-z0-9]/.test(normalized) ? normalized : `config-${normalized}`;
}

function shorten(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  const edge = Math.max(3, Math.floor((maxLength - 1) / 2));
  return `${value.slice(0, edge)}…${value.slice(-edge)}`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatRelative(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  const seconds = Math.round((date.valueOf() - Date.now()) / 1_000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed.";
}
