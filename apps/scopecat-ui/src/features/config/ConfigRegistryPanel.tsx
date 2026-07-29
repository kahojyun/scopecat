import { LoaderCircle, Search } from "lucide-react";
import type { ConfigRegistryEntry, ConfigRegistryOverview } from "../../api-contract";
import { formatRelative, shorten } from "../../lib/presentation";
import { classes } from "../../ui/styles";
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
    <aside
      className="flex min-w-0 flex-col border-r border-line bg-panel-soft px-[11px] pt-[13px] pb-[11px] max-[880px]:mb-2.5 max-[880px]:rounded-lg max-[880px]:border max-[880px]:border-line"
      aria-label="Saved versions"
    >
      <div className="flex items-center justify-between px-[5px] pb-[13px]">
        <div className="grid gap-[3px]">
          <span className="text-[0.57rem] font-extrabold tracking-[0.09em] text-text-dim uppercase">
            Saved versions
          </span>
          <strong className="text-[0.77rem]">{overview.entries.length} versions</strong>
        </div>
        {refreshing && (
          <LoaderCircle
            className="animate-spin text-text-dim"
            size={16}
            aria-label="Refreshing configuration"
          />
        )}
      </div>
      <label className="flex min-h-[38px] items-center gap-2 rounded-[8px] border border-line bg-bg px-2.5 text-text-dim focus-within:border-[rgb(128_163_207_/_45%)]">
        <Search size={15} aria-hidden="true" />
        <span className="sr-only">Search saved versions</span>
        <input
          className="w-full min-w-0 border-0 bg-transparent p-0 text-[0.72rem] text-text outline-0"
          type="search"
          placeholder="Find version"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </label>
      <div className="mt-2.5 grid max-h-[355px] gap-1.5 overflow-auto p-px [scrollbar-color:#344252_transparent] [scrollbar-width:thin] max-[880px]:max-h-[300px]">
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
      className={classes(
        "grid min-h-[62px] cursor-pointer grid-cols-[8px_minmax(0,1fr)_auto] items-start gap-[9px] rounded-md border border-transparent bg-transparent p-2 text-left text-text hover:border-line hover:bg-[rgb(255_255_255_/_2%)]",
        selected && "border-line-strong bg-panel-strong",
      )}
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
    >
      <span
        className={classes(
          "mt-[5px] size-[7px] rounded-full",
          active ? "bg-accent" : "bg-text-dim",
        )}
      />
      <span className="grid min-w-0 gap-[3px]">
        <strong className="overflow-hidden text-[0.71rem] text-ellipsis whitespace-nowrap">
          {entry.id}
        </strong>
        <small className="overflow-hidden text-[0.57rem] text-ellipsis whitespace-nowrap text-text-dim">
          {configSourceLabel(entry)}
          {entry.recorded_at ? ` · ${formatRelative(entry.recorded_at)}` : ""}
        </small>
        <code className="overflow-hidden text-[0.57rem] text-ellipsis whitespace-nowrap text-text-dim">
          {shorten(entry.content_hash, 22)}
        </code>
      </span>
      {active && (
        <span className="rounded-[5px] border border-[rgb(128_163_207_/_18%)] bg-accent-soft px-[5px] py-[3px] text-[0.52rem] font-extrabold text-accent uppercase">
          Default
        </span>
      )}
    </button>
  );
}
