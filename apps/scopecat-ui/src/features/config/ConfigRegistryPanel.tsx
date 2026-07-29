import { LoaderCircle, Search } from "lucide-react";
import type { ConfigRegistryEntry, ConfigRegistryOverview } from "../../api-contract";
import { formatRelative, shorten } from "../../lib/presentation";
import { ConfigInlineEmpty } from "./ConfigUi";
import { configSourceLabel } from "./config-utils";

export function ConfigRegistryPanel({
  overview,
  entries,
  selectedId,
  search,
  refreshing,
  onSearchChange,
  onSelectEntry,
}: {
  overview: ConfigRegistryOverview;
  entries: ConfigRegistryEntry[];
  selectedId?: string;
  search: string;
  refreshing: boolean;
  onSearchChange: (search: string) => void;
  onSelectEntry: (entryId: string) => void;
}) {
  return (
    <aside className="config-registry-panel" aria-label="Saved versions">
      <div className="config-panel-heading">
        <div>
          <span>Saved versions</span>
          <strong>{overview.entries.length} versions</strong>
        </div>
        {refreshing && (
          <LoaderCircle className="animate-spin" size={16} aria-label="Refreshing configuration" />
        )}
      </div>
      <label className="config-search">
        <Search size={15} aria-hidden="true" />
        <span className="sr-only">Search saved versions</span>
        <input
          type="search"
          placeholder="Find version"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </label>
      <div className="config-entry-list">
        {overview.entries.length === 0 ? (
          <ConfigInlineEmpty
            title="No saved versions"
            detail="Bootstrap the project configuration, or use Advanced to import a complete snapshot."
          />
        ) : entries.length === 0 ? (
          <ConfigInlineEmpty
            title="No matching entries"
            detail="Try another id, operator, source run, or note."
          />
        ) : (
          entries.map((entry) => (
            <RegistryEntryButton
              key={entry.id}
              entry={entry}
              active={entry.id === overview.activation?.entry_id}
              selected={entry.id === selectedId}
              onSelect={() => onSelectEntry(entry.id)}
            />
          ))
        )}
      </div>
    </aside>
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
          {configSourceLabel(entry)}
          {entry.recorded_at ? ` · ${formatRelative(entry.recorded_at)}` : ""}
        </small>
        <code>{shorten(entry.content_hash, 22)}</code>
      </span>
      {active && <span className="active-label">Default</span>}
    </button>
  );
}
