import { useRef, useState, type ChangeEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ConfigProfileSnapshot, ConfigRegistryOverview } from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { useConfirmationDialog } from "../../ui/ConfirmationDialog";
import {
  activateConfigEntry,
  importConfigProfile,
  parseConfigProfileJson,
  rollbackConfig,
} from "./config-api";
import { safeConfigEntryId } from "./config-utils";

export type ConfigMutation =
  | { kind: "activate-entry"; entryId: string }
  | { kind: "rollback" }
  | { kind: "import"; draft: ImportDraft };

export interface ImportDraft {
  fileName: string;
  entryId: string;
  config: ConfigProfileSnapshot;
}

export function useConfigMutationWorkflow(overview?: ConfigRegistryOverview) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [operator, setOperator] = useState("local-operator");
  const [note, setNote] = useState("");
  const [importDraft, setImportDraft] = useState<ImportDraft>();
  const [importError, setImportError] = useState<string>();
  const { requestConfirmation, confirmationDialog } = useConfirmationDialog();
  const generation = overview?.active_state?.generation ?? 0;

  const mutation = useMutation({
    mutationFn: async (action: ConfigMutation) => {
      const command = {
        operator: operator.trim(),
        note: note.trim(),
        expected_generation: generation,
      };
      if (!command.operator) {
        throw new Error("Enter an operator name before changing configuration.");
      }
      switch (action.kind) {
        case "activate-entry":
          await activateConfigEntry({ ...command, entry_id: action.entryId });
          return;
        case "rollback":
          await rollbackConfig(command);
          return;
        case "import":
          await importConfigProfile({
            entry_id: action.draft.entryId,
            registered_by: command.operator,
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

  const runAction = (action: ConfigMutation, confirmation: string) => {
    requestConfirmation({
      title: action.kind === "rollback" ? "Restore the previous default?" : "Change the default?",
      description: confirmation,
      confirmLabel: action.kind === "rollback" ? "Restore default" : "Set as default",
      onConfirm: () => mutation.mutate(action),
    });
  };
  const readImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setImportError(undefined);
    try {
      const config = parseConfigProfileJson(await file.text());
      const suggestedEntryId =
        typeof config.id === "string" ? config.id : file.name.replace(/\.[^.]+$/, "");
      setImportDraft({
        fileName: file.name,
        entryId: safeConfigEntryId(suggestedEntryId),
        config,
      });
    } catch (error) {
      setImportError(errorMessage(error));
    }
  };

  return {
    fileInput,
    operator,
    setOperator,
    note,
    setNote,
    importDraft,
    setImportDraft,
    importError,
    mutation,
    commandDisabled: mutation.isPending || !operator.trim(),
    runAction,
    readImport,
    dismissError: () => {
      setImportError(undefined);
      mutation.reset();
    },
    confirmationDialog,
  };
}
