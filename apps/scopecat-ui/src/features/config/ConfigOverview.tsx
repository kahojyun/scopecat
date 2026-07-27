import { GitCompareArrows, History, LoaderCircle, RotateCcw } from "lucide-react";
import type { ConfigActivationRecord, ConfigRegistryOverview } from "../../api-contract";
import { formatDateTime, shorten } from "../../lib/presentation";
import { ConfigInlineEmpty } from "./ConfigUi";

export function ConfigSummary({
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
  const active = overview.activation;
  const history = overview.activation_history;
  const defaultEntry = overview.entries.find((entry) => entry.id === active?.entry_id);
  const runtimeDerived =
    defaultEntry?.source.kind === "manual_parameter_updates" ||
    defaultEntry?.source.kind === "candidate_config";
  return (
    <div className="config-summary" aria-label="Configuration summary">
      <div className="config-summary-default">
        <span>Default</span>
        <strong data-testid="active-config-entry" title={active?.entry_id}>
          {active?.entry_id ?? "Not configured"}
        </strong>
        <code title={active?.entry_content_hash}>
          {active ? shorten(active.entry_content_hash, 16) : "No content hash"}
        </code>
      </div>
      <dl className="config-summary-facts">
        <div>
          <dt>Saved versions</dt>
          <dd>{overview.entries.length}</dd>
        </div>
        <div>
          <dt>Default changes</dt>
          <dd>{history.length}</dd>
        </div>
      </dl>
      <div className="config-summary-rollback">
        <span>Previous</span>
        <strong title={history[1]?.entry_id}>{history[1]?.entry_id ?? "Nothing to undo"}</strong>
        <button
          className="secondary-button"
          type="button"
          disabled={rollbackDisabled}
          onClick={onRollback}
        >
          {rollbackPending ? <LoaderCircle className="spin" size={15} /> : <RotateCcw size={15} />}
          Undo
        </button>
      </div>
      {runtimeDerived && (
        <aside className="runtime-derived-default" role="note">
          <GitCompareArrows size={17} aria-hidden="true" />
          <div>
            <strong>Runtime-derived default</strong>
            <p>
              This console cannot tell whether the project&apos;s Git/Python configuration source is
              synchronized. Run <code>scopecat config diff .</code> to check.
            </p>
          </div>
        </aside>
      )}
    </div>
  );
}

export function ActivationHistory({ history }: { history: ConfigActivationRecord[] }) {
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
                <strong>{record.entry_id}</strong>
                <small>
                  {record.operator || "Unknown operator"}
                  {record.recorded_at ? ` · ${formatDateTime(record.recorded_at)}` : ""}
                </small>
                {record.note && <p>{record.note}</p>}
              </div>
              <code>{shorten(record.entry_content_hash, 18)}</code>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
