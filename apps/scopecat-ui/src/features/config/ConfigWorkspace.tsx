import { useState } from "react";
import { Menu } from "@base-ui/react/menu";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CircleDot,
  Database,
  FileUp,
  LoaderCircle,
  RefreshCw,
  SlidersHorizontal,
  UserRound,
  X,
  XCircle,
} from "lucide-react";
import { errorMessage } from "../../lib/presentation";
import { ConfigDraftEditor, type ConfigDraftSeed } from "./ConfigDraftEditor";
import { ConfigEntryInspector } from "./ConfigEntryInspector";
import { ConfigImportDialog } from "./ConfigImportDialog";
import { ActivationHistory, ConfigSummary } from "./ConfigOverview";
import { ConfigRegistryPanel } from "./ConfigRegistryPanel";
import { ConfigBoundaryMessage } from "./ConfigUi";
import { useConfigMutationWorkflow } from "./useConfigMutationWorkflow";
import { useConfigRegistry } from "./useConfigRegistry";

export function ConfigWorkspace({
  daemonUnavailable,
  onOpenRun,
}: {
  daemonUnavailable: boolean;
  onOpenRun?: (runId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [configDraft, setConfigDraft] = useState<ConfigDraftSeed>();
  const registry = useConfigRegistry(daemonUnavailable);
  const workflow = useConfigMutationWorkflow(registry.overview);

  const selectEntry = (entryId: string) => {
    registry.selectEntry(entryId);
    workflow.mutation.reset();
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
  if (registry.registryQuery.isPending) {
    return (
      <ConfigBoundaryMessage
        icon={<LoaderCircle className="spin" />}
        title="Reading saved configurations"
        detail="Loading the default snapshot, saved versions, and change history."
      />
    );
  }
  if (registry.registryQuery.isError) {
    return (
      <ConfigBoundaryMessage
        icon={<XCircle />}
        title="Configuration registry unavailable"
        detail={errorMessage(registry.registryQuery.error)}
        warning
        action={
          <button
            className="secondary-button"
            type="button"
            onClick={() => void registry.registryQuery.refetch()}
          >
            <RefreshCw size={15} aria-hidden="true" />
            Retry
          </button>
        }
      />
    );
  }
  const overview = registry.overview;
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

  const selectedEntry = registry.selectedEntry;
  const commandDisabled = workflow.commandDisabled;
  const editableDraftSeed =
    selectedEntry &&
    overview.activation &&
    registry.entryDetailQuery.data?.config &&
    overview.activation.entry_id === selectedEntry.id
      ? {
          entry: selectedEntry,
          active: overview.activation,
          config: registry.entryDetailQuery.data.config,
        }
      : undefined;
  return (
    <section className="config-workspace" aria-labelledby="config-heading">
      <header className="config-toolbar">
        <div>
          <h2 id="config-heading">Default configuration</h2>
        </div>
        <div className="config-toolbar-actions">
          <label className="operator-field">
            <UserRound size={15} aria-hidden="true" />
            <span className="visually-hidden">Operator name</span>
            <input
              value={workflow.operator}
              onChange={(event) => workflow.setOperator(event.target.value)}
              placeholder="Operator"
              autoComplete="name"
            />
          </label>
          <input
            ref={workflow.fileInput}
            className="visually-hidden"
            type="file"
            accept=".json,application/json"
            onChange={(event) => void workflow.readImport(event)}
          />
          <Menu.Root>
            <Menu.Trigger className="secondary-button action-menu-trigger">
              <SlidersHorizontal size={15} aria-hidden="true" />
              Advanced
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Positioner className="action-menu-positioner" sideOffset={6} align="end">
                <Menu.Popup className="action-menu-popup">
                  <Menu.Item
                    className="action-menu-item"
                    onClick={() => workflow.fileInput.current?.click()}
                  >
                    <FileUp size={15} aria-hidden="true" />
                    <span>
                      <strong>Import raw snapshot</strong>
                      <small>Bypass the typed parameter editor.</small>
                    </span>
                  </Menu.Item>
                </Menu.Popup>
              </Menu.Positioner>
            </Menu.Portal>
          </Menu.Root>
        </div>
      </header>

      {(workflow.importError || workflow.mutation.error) && (
        <div className="config-error" role="status">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>{workflow.importError ?? errorMessage(workflow.mutation.error)}</span>
          <button type="button" aria-label="Dismiss error" onClick={workflow.dismissError}>
            <X size={15} />
          </button>
        </div>
      )}

      <ConfigSummary
        overview={overview}
        rollbackDisabled={
          commandDisabled ||
          overview.activation_history.length < 2 ||
          overview.activation === undefined
        }
        rollbackPending={
          workflow.mutation.isPending && workflow.mutation.variables?.kind === "rollback"
        }
        onRollback={() =>
          workflow.runAction(
            { kind: "rollback" },
            `Restore ${
              overview.activation_history[1]?.entry_id ?? "the previous version"
            } as the default configuration?`,
          )
        }
      />

      <div className="config-layout">
        <ConfigRegistryPanel
          overview={overview}
          entries={registry.filteredEntries}
          selectedId={registry.selectedId}
          search={registry.registrySearch}
          refreshing={registry.registryQuery.isFetching}
          onSearchChange={registry.setRegistrySearch}
          onSelectEntry={selectEntry}
        />

        <section className="config-inspector" aria-live="polite">
          {selectedEntry ? (
            <ConfigEntryInspector
              entry={selectedEntry}
              active={overview.activation?.entry_id === selectedEntry.id}
              snapshot={registry.entryDetailQuery.data?.summary}
              config={registry.entryDetailQuery.data?.config}
              activeConfig={registry.activeDetailQuery.data?.config}
              snapshotPending={registry.entryDetailQuery.isPending}
              snapshotError={registry.entryDetailQuery.error}
              note={workflow.note}
              pending={
                workflow.mutation.isPending &&
                workflow.mutation.variables?.kind === "activate-entry"
              }
              actionDisabled={commandDisabled}
              onNoteChange={workflow.setNote}
              onSelectEntry={selectEntry}
              onOpenRun={onOpenRun}
              onActivate={() =>
                workflow.runAction(
                  { kind: "activate-entry", entryId: selectedEntry.id },
                  `Set ${selectedEntry.id} as the default configuration?`,
                )
              }
              onEdit={editableDraftSeed ? () => setConfigDraft(editableDraftSeed) : undefined}
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
          currentActive={overview.activation ?? undefined}
          operator={workflow.operator}
          onCancel={() => setConfigDraft(undefined)}
          onRegistered={async (receipt) => {
            setConfigDraft(undefined);
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["config"] }),
              queryClient.invalidateQueries({ queryKey: ["events"] }),
            ]);
            registry.selectEntry(receipt.entry.id);
          }}
        />
      )}

      <ActivationHistory history={overview.activation_history} />

      {workflow.importDraft && (
        <ConfigImportDialog
          draft={workflow.importDraft}
          note={workflow.note}
          pending={workflow.mutation.isPending && workflow.mutation.variables?.kind === "import"}
          disabled={workflow.mutation.isPending || !workflow.operator.trim()}
          onChange={workflow.setImportDraft}
          onNoteChange={workflow.setNote}
          onCancel={() => workflow.setImportDraft(undefined)}
          onSubmit={() =>
            workflow.mutation.mutate({
              kind: "import",
              draft: workflow.importDraft!,
            })
          }
        />
      )}
      {workflow.confirmationDialog}
    </section>
  );
}
