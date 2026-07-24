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
import { ApiError, getRunAnalyses } from "./api";
import {
  activateConfigEntry,
  getConfigRegistry,
  getConfigRegistryEntry,
  importConfigProfile,
  parseConfigProfileJson,
  rollbackConfig,
} from "./config-api";
import {
  ConfigDraftEditor,
  type ConfigDraftSeed,
} from "./ConfigDraftEditor";
import { ConfigParameters } from "./ConfigParameters";
import {
  getRunParameterProposals,
  latestProposalDecision,
} from "./proposal-api";
import type {
  ConfigActivationRecord,
  ConfigProfileSnapshot,
  ConfigRegistryEntry,
  ConfigRegistryOverview,
  ConfigSnapshotSummary,
  JsonObject,
} from "./config-types";
import type { ParameterProposal } from "./proposal-types";
import type { RunAnalysis } from "./types";

type ConfigMutation =
  | { kind: "activate-entry"; entryId: string }
  | { kind: "rollback" }
  | { kind: "import"; draft: ImportDraft };

interface ImportDraft {
  fileName: string;
  entryId: string;
  config: JsonObject;
}

export function ConfigWorkspace({
  daemonUnavailable,
  onOpenRun,
}: {
  daemonUnavailable: boolean;
  onOpenRun?: (runId: string) => void;
}) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [selectedId, setSelectedId] = useState<string>();
  const [registrySearch, setRegistrySearch] = useState("");
  const [operator, setOperator] = useState("local-operator");
  const [note, setNote] = useState("");
  const [importDraft, setImportDraft] = useState<ImportDraft>();
  const [importError, setImportError] = useState<string>();
  const [configDraft, setConfigDraft] = useState<ConfigDraftSeed>();

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
  const activeEntry = overview?.entries.find(
    (entry) => entry.id === overview.active?.entryId,
  );
  const entryDetailQuery = useQuery({
    queryKey: [
      "config",
      "entry",
      selectedEntry?.id,
      selectedEntry?.contentHash,
    ],
    queryFn: ({ signal }) => getConfigRegistryEntry(selectedEntry!.id, signal),
    enabled: selectedEntry !== undefined,
    staleTime: Infinity,
  });
  const activeDetailQuery = useQuery({
    queryKey: [
      "config",
      "entry",
      activeEntry?.id,
      activeEntry?.contentHash,
    ],
    queryFn: ({ signal }) => getConfigRegistryEntry(activeEntry!.id, signal),
    enabled: activeEntry !== undefined,
    staleTime: Infinity,
  });
  const candidateRunId =
    selectedEntry?.source.kind === "candidate_config"
      ? selectedEntry.source.runId
      : undefined;
  const candidateProposalsQuery = useQuery({
    queryKey: ["parameter-proposals", candidateRunId],
    queryFn: ({ signal }) =>
      getRunParameterProposals(candidateRunId!, signal),
    enabled: candidateRunId !== undefined,
  });
  const candidateAnalysesQuery = useQuery({
    queryKey: ["analyses", candidateRunId],
    queryFn: ({ signal }) => getRunAnalyses(candidateRunId!, signal),
    enabled: candidateRunId !== undefined,
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
        title="Reading saved configurations"
        detail="Loading the default snapshot, saved versions, and change history."
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
          <p className="eyebrow">Configuration history</p>
          <h2 id="config-heading">Default configuration</h2>
          <p>
            Browse typed parameters, compare saved versions, and choose the
            default used by new runs.
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
          <details className="config-advanced-menu">
            <summary>
              <SlidersHorizontal size={15} aria-hidden="true" />
              Advanced
            </summary>
            <div>
              <button
                className="secondary-button"
                type="button"
                onClick={() => fileInput.current?.click()}
              >
                <FileUp size={15} aria-hidden="true" />
                Import raw snapshot
              </button>
              <small>
                Direct JSON import bypasses the typed parameter editor.
              </small>
            </div>
          </details>
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
            `Restore ${
              overview.history[1]?.entryId ?? "the previous version"
            } as the default configuration?`,
          )
        }
      />

      <div className="config-layout">
        <aside className="config-registry-panel" aria-label="Saved versions">
          <div className="config-panel-heading">
            <div>
              <span>Saved versions</span>
              <strong>{overview.entries.length} versions</strong>
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
            <span className="visually-hidden">Search saved versions</span>
            <input
              type="search"
              placeholder="Find version"
              value={registrySearch}
              onChange={(event) => setRegistrySearch(event.target.value)}
            />
          </label>
          <div className="config-entry-list">
            {overview.entries.length === 0 ? (
              <ConfigInlineEmpty
                title="No saved versions"
                detail="Bootstrap the project configuration, or use Advanced to import a complete snapshot."
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
              snapshot={entryDetailQuery.data?.summary}
              config={entryDetailQuery.data?.config}
              activeConfig={activeDetailQuery.data?.config}
              snapshotPending={entryDetailQuery.isPending}
              snapshotError={entryDetailQuery.error}
              note={note}
              pending={
                mutation.isPending &&
                mutation.variables?.kind === "activate-entry"
              }
              actionDisabled={commandDisabled}
              onNoteChange={setNote}
              onSelectEntry={selectEntry}
              onOpenRun={onOpenRun}
              candidateProposals={candidateProposalsQuery.data?.items}
              candidateProposalsPending={candidateProposalsQuery.isPending}
              candidateProposalsError={candidateProposalsQuery.error}
              candidateAnalyses={candidateAnalysesQuery.data}
              candidateAnalysesPending={candidateAnalysesQuery.isPending}
              candidateAnalysesError={candidateAnalysesQuery.error}
              onActivate={() =>
                runAction(
                  { kind: "activate-entry", entryId: selectedEntry.id },
                  `Set ${selectedEntry.id} as the default configuration?`,
                )
              }
              onEdit={
                overview.active &&
                entryDetailQuery.data?.config &&
                overview.active.entryId === selectedEntry.id
                  ? () =>
                      setConfigDraft({
                        entry: selectedEntry,
                        active: overview.active!,
                        config: entryDetailQuery.data!.config,
                      })
                  : undefined
              }
            />
          ) : (
            <ConfigBoundaryMessage
              icon={<CircleDot />}
              title="Nothing selected"
              detail="Choose a saved version to inspect its immutable snapshot."
              compact
            />
          )}
        </section>
      </div>

      {configDraft && (
        <ConfigDraftEditor
          seed={configDraft}
          currentActive={overview.active}
          operator={operator}
          onCancel={() => setConfigDraft(undefined)}
          onRegistered={async (receipt) => {
            setConfigDraft(undefined);
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["config"] }),
              queryClient.invalidateQueries({ queryKey: ["events"] }),
            ]);
            setSelectedId(receipt.entry.id);
          }}
        />
      )}

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
  const defaultEntry = overview.entries.find(
    (entry) => entry.id === overview.active?.entryId,
  );
  const runtimeDerived =
    defaultEntry?.source.kind === "manual_parameter_updates" ||
    defaultEntry?.source.kind === "candidate_config";
  return (
    <div className="config-summary-grid" aria-label="Configuration summary">
      <article className="active-config-card">
        <span className="config-summary-icon">
          <CheckCircle2 size={18} />
        </span>
        <div>
          <span>Default configuration</span>
          <strong>{overview.active?.entryId ?? "Not configured"}</strong>
          <code title={overview.active?.contentHash}>
            {overview.active
              ? shorten(overview.active.contentHash, 23)
              : "No default content hash"}
          </code>
        </div>
      </article>
      <ConfigMetric
        icon={<Database size={17} />}
        label="Saved versions"
        value={String(overview.entries.length)}
        detail="Immutable history"
      />
      <ConfigMetric
        icon={<History size={17} />}
        label="Default changes"
        value={String(overview.history.length)}
        detail="Durable history"
      />
      <article className="rollback-card">
        <div>
          <span>Previous default</span>
          <strong>
            {overview.history[1]?.entryId ?? "Nothing to undo"}
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
          Undo
        </button>
      </article>
      {runtimeDerived && (
        <aside className="runtime-derived-default" role="note">
          <GitCompareArrows size={17} aria-hidden="true" />
          <div>
            <strong>Runtime-derived default</strong>
            <p>
              This console cannot tell whether the project&apos;s Git/Python
              configuration source is synchronized. Run{" "}
              <code>scopecat config diff .</code> to check.
            </p>
          </div>
        </aside>
      )}
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
      {active && <span className="active-label">Default</span>}
    </button>
  );
}

function EntryInspector({
  entry,
  active,
  snapshot,
  config,
  activeConfig,
  snapshotPending,
  snapshotError,
  note,
  pending,
  actionDisabled,
  onNoteChange,
  onSelectEntry,
  onOpenRun,
  candidateProposals,
  candidateProposalsPending,
  candidateProposalsError,
  candidateAnalyses,
  candidateAnalysesPending,
  candidateAnalysesError,
  onActivate,
  onEdit,
}: {
  entry: ConfigRegistryEntry;
  active: boolean;
  snapshot?: ConfigSnapshotSummary;
  config?: ConfigProfileSnapshot;
  activeConfig?: ConfigProfileSnapshot;
  snapshotPending: boolean;
  snapshotError: Error | null;
  note: string;
  pending: boolean;
  actionDisabled: boolean;
  onNoteChange: (note: string) => void;
  onSelectEntry: (entryId: string) => void;
  onOpenRun?: (runId: string) => void;
  candidateProposals?: ParameterProposal[];
  candidateProposalsPending: boolean;
  candidateProposalsError: Error | null;
  candidateAnalyses?: RunAnalysis[];
  candidateAnalysesPending: boolean;
  candidateAnalysesError: Error | null;
  onActivate: () => void;
  onEdit?: () => void;
}) {
  const selectedSnapshot = snapshot;
  return (
    <>
      <header className="config-inspector-heading">
        <div>
          <span className={active ? "config-state active" : "config-state"}>
            {active ? "Default" : "Saved"}
          </span>
          <h3>{entry.id}</h3>
          <code title={entry.contentHash}>{entry.contentHash}</code>
        </div>
        {active && onEdit && (
          <button
            className="primary-button"
            type="button"
            onClick={onEdit}
          >
            <SlidersHorizontal size={15} />
            Edit parameters
          </button>
        )}
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
            Set as default
          </button>
        )}
      </header>
      <div className="config-detail-facts">
        <ConfigFact label="Source" value={sourceLabel(entry)} />
        <ConfigFact
          label="Saved by"
          value={entry.registeredBy ?? "Not reported"}
        />
        <ConfigFact
          label="Saved"
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
      <EntryProvenance
        entry={entry}
        onSelectEntry={onSelectEntry}
        onOpenRun={onOpenRun}
        candidateProposals={candidateProposals}
        candidateProposalsPending={candidateProposalsPending}
        candidateProposalsError={candidateProposalsError}
        candidateAnalyses={candidateAnalyses}
        candidateAnalysesPending={candidateAnalysesPending}
        candidateAnalysesError={candidateAnalysesError}
      />
      {selectedSnapshot ? (
        <>
          <SnapshotSummary snapshot={selectedSnapshot} />
          {config && (
            <ConfigParameters config={config} activeConfig={activeConfig} />
          )}
        </>
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
          <span>Save note</span>
          <p>{entry.note}</p>
        </div>
      )}
      {!active && (
        <ActionNote value={note} onChange={onNoteChange} />
      )}
    </>
  );
}

function EntryProvenance({
  entry,
  onSelectEntry,
  onOpenRun,
  candidateProposals,
  candidateProposalsPending,
  candidateProposalsError,
  candidateAnalyses,
  candidateAnalysesPending,
  candidateAnalysesError,
}: {
  entry: ConfigRegistryEntry;
  onSelectEntry: (entryId: string) => void;
  onOpenRun?: (runId: string) => void;
  candidateProposals?: ParameterProposal[];
  candidateProposalsPending: boolean;
  candidateProposalsError: Error | null;
  candidateAnalyses?: RunAnalysis[];
  candidateAnalysesPending: boolean;
  candidateAnalysesError: Error | null;
}) {
  const source = entry.source;
  if (source.kind === "direct_config_profile") {
    return (
      <div className="config-provenance">
        <GitCompareArrows size={16} aria-hidden="true" />
        <div>
          <strong>Direct configuration profile</strong>
          <p>Saved from one complete config snapshot.</p>
        </div>
      </div>
    );
  }
  if (source.kind === "manual_parameter_updates") {
    return (
      <div className="config-provenance">
        <GitCompareArrows size={16} aria-hidden="true" />
        <div>
          <strong>Manual parameter update</strong>
          <p>
            Derived from{" "}
            {source.baseEntryId ? (
              <button
                className="config-provenance-link"
                type="button"
                aria-label={`Open base version ${source.baseEntryId}`}
                onClick={() => onSelectEntry(source.baseEntryId!)}
              >
                <code>{source.baseEntryId}</code>
              </button>
            ) : (
              "an unreported base version"
            )}
            {source.baseGeneration
              ? ` at registry generation ${source.baseGeneration}.`
              : "."}
          </p>
        </div>
      </div>
    );
  }

  const runId = source.runId;
  const proposalsById = new Map(
    (candidateProposals ?? []).map((proposal) => [proposal.id, proposal]),
  );
  const analysesById = new Map(
    (candidateAnalyses ?? []).map((analysis) => [analysis.id, analysis]),
  );
  return (
    <div className="config-provenance candidate-provenance">
      <GitCompareArrows size={16} aria-hidden="true" />
      <div>
        <div className="config-provenance-heading">
          <div>
            <strong>Analysis candidate</strong>
            <p>
              Produced by run{" "}
              <code>{runId ?? "unreported producing run"}</code>.
            </p>
          </div>
          {runId && onOpenRun && (
            <button
              className="secondary-button"
              type="button"
              onClick={() => onOpenRun(runId)}
            >
              Open producing run
            </button>
          )}
        </div>

        {candidateProposalsError && (
          <p className="candidate-evidence-status">
            Proposal evidence unavailable:{" "}
            {errorMessage(candidateProposalsError)}
          </p>
        )}
        {candidateAnalysesError && (
          <p className="candidate-evidence-status">
            Analysis details unavailable: {errorMessage(candidateAnalysesError)}
          </p>
        )}

        <div className="candidate-evidence-list">
          {source.proposalIds.length === 0 && (
            <p className="candidate-evidence-status">
              No proposal evidence is recorded for this candidate.
            </p>
          )}
          {source.proposalIds.map((proposalId) => {
            const proposal = proposalsById.get(proposalId);
            const analysis = proposal
              ? analysesById.get(proposal.analysisRecordId)
              : undefined;
            const decision = proposal
              ? latestProposalDecision(proposal)
              : undefined;
            return (
              <article
                key={proposalId}
                aria-label={`Proposal ${proposalId}`}
              >
                <dl>
                  <div>
                    <dt>Proposal</dt>
                    <dd>
                      <code>{proposalId}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Analysis</dt>
                    <dd>
                      {proposal ? (
                        <>
                          <code>{proposal.analysisRecordId}</code>
                          {analysis && <span>{analysis.title}</span>}
                          {!analysis &&
                            candidateAnalysesPending &&
                            " · Loading details"}
                        </>
                      ) : candidateProposalsPending ? (
                        "Loading proposal"
                      ) : (
                        "Proposal details unavailable"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>
                      {decision?.decision === "approved"
                        ? "Latest acceptance"
                        : "Latest decision"}
                    </dt>
                    <dd>
                      {decision
                        ? `${displayDecision(decision.decision)} · ${decisionAuthorityLabel(
                            decision,
                          )}`
                        : candidateProposalsPending
                          ? "Loading decision"
                          : "Decision unavailable"}
                    </dd>
                  </div>
                  {decision && (
                    <>
                      <div>
                        <dt>Note</dt>
                        <dd>{decision.note || "No decision note"}</dd>
                      </div>
                      <div>
                        <dt>Decided</dt>
                        <dd>
                          {decision.decidedAt ? (
                            <time dateTime={decision.decidedAt}>
                              {formatDateTime(decision.decidedAt)}
                            </time>
                          ) : (
                            "Decision time unavailable"
                          )}
                        </dd>
                      </div>
                    </>
                  )}
                </dl>
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function decisionAuthorityLabel(
  decision: NonNullable<
    ReturnType<typeof latestProposalDecision>
  >,
): string {
  if (decision.authorityKind === "automatic_policy") {
    const policy =
      decision.policyId && decision.policyVersion
        ? `${decision.policyId}@${decision.policyVersion}`
        : "unidentified policy";
    return `Automatic policy ${policy} · ${decision.actor}`;
  }
  return `Human · ${decision.actor}`;
}

function displayDecision(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");
}

function SnapshotSummary({ snapshot }: { snapshot: ConfigSnapshotSummary }) {
  return (
    <section className="snapshot-summary" aria-label="Snapshot summary">
      <div className="snapshot-heading">
        <SlidersHorizontal size={17} aria-hidden="true" />
        <span>
          <strong>{snapshot.id}</strong>
          <small>Immutable config snapshot</small>
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
          <h3 id="history-heading">Default history</h3>
          <p>Every default change is retained and can be revisited.</p>
        </div>
        <span className="history-count">{history.length}</span>
      </header>
      {history.length === 0 ? (
        <ConfigInlineEmpty
          title="No default history"
          detail="The first default configuration will appear here."
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
            <p>Advanced raw import · {draft.fileName}</p>
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
            Import raw snapshot
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
  if (entry.source.kind === "candidate_config") return "Candidate config";
  if (entry.source.kind === "manual_parameter_updates") {
    return "Typed parameter edit";
  }
  return "Direct profile";
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
