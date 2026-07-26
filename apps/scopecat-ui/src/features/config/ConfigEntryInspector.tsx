import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, GitCompareArrows, LoaderCircle, SlidersHorizontal } from "lucide-react";
import { getRunAnalyses } from "../../api";
import type { ConfigProfileSnapshot, ConfigRegistryEntry } from "../../api-contract";
import { getRunParameterProposals } from "../../data/parameter-proposals/api";
import type { ParameterProposal } from "../../data/parameter-proposals/types";
import { errorMessage, formatDateTime, shorten } from "../../lib/presentation";
import type { RunAnalysis } from "../../types";
import { ConfigParameters } from "./ConfigParameters";
import { ActionNote, ConfigFact, ConfigInlineEmpty } from "./ConfigUi";
import type { ConfigSnapshotSummary } from "./config-api";
import { configSourceLabel } from "./config-utils";

export function ConfigEntryInspector({
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
  onActivate: () => void;
  onEdit?: () => void;
}) {
  const candidateRunId = entry.source.kind === "candidate_config" ? entry.source.run_id : undefined;
  const candidateProposalsQuery = useQuery({
    queryKey: ["parameter-proposals", candidateRunId],
    queryFn: ({ signal }) => getRunParameterProposals(candidateRunId!, signal),
    enabled: candidateRunId !== undefined,
  });
  const candidateAnalysesQuery = useQuery({
    queryKey: ["analyses", candidateRunId],
    queryFn: ({ signal }) => getRunAnalyses(candidateRunId!, signal),
    enabled: candidateRunId !== undefined,
  });

  return (
    <>
      <header className="config-inspector-heading">
        <div>
          <span className={active ? "config-state active" : "config-state"}>
            {active ? "Default" : "Saved"}
          </span>
          <h3 title={entry.id}>{shorten(entry.id, 44)}</h3>
          <code title={entry.content_hash}>{entry.content_hash}</code>
        </div>
        {active && onEdit && (
          <button className="primary-button" type="button" onClick={onEdit}>
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
            {pending ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}
            Set as default
          </button>
        )}
      </header>
      <div className="config-detail-facts">
        <ConfigFact label="Source" value={configSourceLabel(entry)} />
        <ConfigFact label="Saved by" value={entry.registered_by || "Not reported"} />
        <ConfigFact
          label="Saved"
          value={entry.registered_at ? formatDateTime(entry.registered_at) : "Not reported"}
        />
        <ConfigFact label="Config ref" value={entry.config_ref || "Not reported"} code />
      </div>
      <EntryProvenance
        entry={entry}
        onSelectEntry={onSelectEntry}
        onOpenRun={onOpenRun}
        candidateProposals={candidateProposalsQuery.data?.items}
        candidateProposalsPending={candidateProposalsQuery.isPending}
        candidateProposalsError={candidateProposalsQuery.error}
        candidateAnalyses={candidateAnalysesQuery.data}
        candidateAnalysesPending={candidateAnalysesQuery.isPending}
        candidateAnalysesError={candidateAnalysesQuery.error}
      />
      {snapshot ? (
        <>
          <SnapshotSummary snapshot={snapshot} />
          {config && <ConfigParameters config={config} activeConfig={activeConfig} />}
        </>
      ) : snapshotPending ? (
        <ConfigInlineEmpty
          title="Reading snapshot"
          detail="Loading this registry entry's immutable config snapshot."
        />
      ) : snapshotError ? (
        <ConfigInlineEmpty title="Snapshot unavailable" detail={errorMessage(snapshotError)} />
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
      {!active && <ActionNote value={note} onChange={onNoteChange} />}
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
            {source.base_entry_id ? (
              <button
                className="config-provenance-link"
                type="button"
                aria-label={`Open base version ${source.base_entry_id}`}
                onClick={() => onSelectEntry(source.base_entry_id)}
              >
                <code>{source.base_entry_id}</code>
              </button>
            ) : (
              "an unreported base version"
            )}
            {source.base_registry_generation
              ? ` at registry generation ${source.base_registry_generation}.`
              : "."}
          </p>
        </div>
      </div>
    );
  }

  const runId = source.run_id;
  const proposalId = source.proposal_id;
  const proposalsById = new Map(
    (candidateProposals ?? []).map((proposal) => [proposal.id, proposal]),
  );
  const analysesById = new Map(
    (candidateAnalyses ?? []).map((analysis) => [analysis.id, analysis]),
  );
  const proposal = proposalsById.get(proposalId);
  const analysis = proposal ? analysesById.get(proposal.analysisRecordId) : undefined;
  const approval = proposal?.approval;
  return (
    <div className="config-provenance candidate-provenance">
      <GitCompareArrows size={16} aria-hidden="true" />
      <div>
        <div className="config-provenance-heading">
          <div>
            <strong>Analysis candidate</strong>
            <p>
              Produced by run <code>{runId ?? "unreported producing run"}</code>.
            </p>
          </div>
          {runId && onOpenRun && (
            <button className="secondary-button" type="button" onClick={() => onOpenRun(runId)}>
              Open producing run
            </button>
          )}
        </div>

        {candidateProposalsError && (
          <p className="candidate-evidence-status">
            Proposal evidence unavailable: {errorMessage(candidateProposalsError)}
          </p>
        )}
        {candidateAnalysesError && (
          <p className="candidate-evidence-status">
            Analysis details unavailable: {errorMessage(candidateAnalysesError)}
          </p>
        )}

        <div className="candidate-evidence-list">
          <article aria-label={`Proposal ${proposalId}`}>
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
                      {!analysis && candidateAnalysesPending && " · Loading details"}
                    </>
                  ) : candidateProposalsPending ? (
                    "Loading proposal"
                  ) : (
                    "Proposal details unavailable"
                  )}
                </dd>
              </div>
              <div>
                <dt>Operator approval</dt>
                <dd>
                  {approval
                    ? `Approved · ${approval.actor}`
                    : candidateProposalsPending
                      ? "Loading approval"
                      : "Approval unavailable"}
                </dd>
              </div>
              {approval && (
                <>
                  <div>
                    <dt>Note</dt>
                    <dd>{approval.note || "No approval note"}</dd>
                  </div>
                  <div>
                    <dt>Approved</dt>
                    <dd>
                      {approval.approvedAt ? (
                        <time dateTime={approval.approvedAt}>
                          {formatDateTime(approval.approvedAt)}
                        </time>
                      ) : (
                        "Approval time unavailable"
                      )}
                    </dd>
                  </div>
                </>
              )}
            </dl>
          </article>
        </div>
      </div>
    </div>
  );
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
        <ConfigFact label="Parameters" value={String(snapshot.parameterCount)} />
        <ConfigFact label="Instruments" value={String(snapshot.instrumentCount)} />
        <ConfigFact label="Primary entity" value={snapshot.primaryEntityId ?? "Not reported"} />
      </div>
    </section>
  );
}
