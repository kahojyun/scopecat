import { useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Eye, LoaderCircle, Pencil, X } from "lucide-react";
import { ApiError } from "../../api";
import { iconButton, primaryButton, secondaryButton } from "../../ui/styles";
import { previewConfigDraft, setConfigDefault } from "./config-api";
import { deriveConfigDraftUpdates } from "./config-draft";
import { ConfigParameters } from "./ConfigParameters";
import { ParameterEditor } from "./ConfigValueEditors";
import type {
  ConfigDraftCommand,
  ConfigDraftPreview,
  ConfigProfileSnapshot,
  ConfigActivationRecord,
  ConfigRegistryEntry,
  ConfigPublishReceipt,
  ParameterUpdate,
  StoredParameterValue,
} from "../../api-contract";

export interface ConfigDraftSeed {
  entry: ConfigRegistryEntry;
  active: ConfigActivationRecord;
  config: ConfigProfileSnapshot;
}

type PendingConfigDraft = Omit<ConfigDraftCommand, "updates"> & {
  updates: ParameterUpdate[];
};

export function ConfigDraftEditor({
  seed,
  currentActive,
  operator,
  onCancel,
  onPublished,
}: {
  seed: ConfigDraftSeed;
  currentActive?: ConfigActivationRecord;
  operator: string;
  onCancel: () => void;
  onPublished: (receipt: ConfigPublishReceipt) => void | Promise<void>;
}) {
  const definitions = seed.config.system.parameter_catalog.definitions ?? [];
  const baseValues = useMemo(
    () => new Map((seed.config.parameter_snapshot.values ?? []).map((value) => [value.id, value])),
    [seed.config],
  );
  const [selectedId, setSelectedId] = useState(definitions[0]?.id);
  const [editedValues, setEditedValues] = useState<Record<string, StoredParameterValue>>({});
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<ConfigDraftPreview>();
  const [invalidFields, setInvalidFields] = useState<Set<string>>(() => new Set());
  const [tableRowOrigins, setTableRowOrigins] = useState<Record<string, Array<"base" | "new">>>({});
  const draftRevision = useRef(0);
  const updates = useMemo(
    () => deriveConfigDraftUpdates(seed.config, editedValues),
    [editedValues, seed.config],
  );
  const draft = useMemo<PendingConfigDraft>(
    () => ({
      base_entry_id: seed.entry.id,
      base_content_hash: seed.active.entry_content_hash,
      base_generation: seed.active.generation,
      candidate_id: `${seed.config.id}-edit`,
      updates,
    }),
    [seed.active, seed.config.id, seed.entry.id, updates],
  );
  const selectedDefinition = definitions.find((definition) => definition.id === selectedId);
  const selectedValue = selectedDefinition
    ? (editedValues[selectedDefinition.id] ?? baseValues.get(selectedDefinition.id))
    : undefined;
  const stale =
    !currentActive ||
    currentActive.entry_id !== seed.active.entry_id ||
    currentActive.entry_content_hash !== seed.active.entry_content_hash ||
    currentActive.generation !== seed.active.generation;

  const previewMutation = useMutation({
    mutationFn: ({ command }: { command: ConfigDraftCommand; revision: number }) =>
      previewConfigDraft(command),
    onSuccess: (result, variables) => {
      if (variables.revision === draftRevision.current) setPreview(result);
    },
  });
  const defaultMutation = useMutation({
    mutationFn: async ({
      command,
      reviewed,
      revision,
      operatorName,
      auditNote,
    }: {
      command: ConfigDraftCommand;
      reviewed?: ConfigDraftPreview;
      revision: number;
      operatorName: string;
      auditNote: string;
    }) => {
      const checked =
        reviewed?.valid && reviewed.result_content_hash
          ? reviewed
          : await previewConfigDraft(command);
      if (!checked.valid || !checked.result_content_hash) {
        return { preview: checked, revision };
      }
      const receipt = await setConfigDefault({
        source: {
          kind: "manual_parameter_updates",
          draft: command,
          expected_result_content_hash: checked.result_content_hash,
        },
        entry_id: defaultDraftEntryId(command.candidate_id, checked.result_content_hash),
        actor: operatorName,
        expected_generation: command.base_generation,
        note: auditNote,
      });
      return { preview: checked, receipt, revision };
    },
    onSuccess: async (result) => {
      if (result.revision === draftRevision.current) {
        setPreview(result.preview);
      }
      if (result.receipt) await onPublished(result.receipt);
    },
  });
  const saving = defaultMutation.isPending;

  const changeValue = (value: StoredParameterValue) => {
    draftRevision.current += 1;
    setEditedValues((current) => ({ ...current, [value.id]: value }));
    setPreview(undefined);
    previewMutation.reset();
    defaultMutation.reset();
  };
  const setFieldValidity = (field: string, valid: boolean) => {
    draftRevision.current += 1;
    setInvalidFields((current) => {
      const next = new Set(current);
      if (valid) next.delete(field);
      else next.add(field);
      return next;
    });
    setPreview(undefined);
    previewMutation.reset();
    defaultMutation.reset();
  };
  const resetParameter = (parameterId: string) => {
    draftRevision.current += 1;
    setEditedValues((current) => {
      const next = { ...current };
      delete next[parameterId];
      return next;
    });
    setPreview(undefined);
    setInvalidFields(new Set());
    setTableRowOrigins((current) => {
      const next = { ...current };
      delete next[parameterId];
      return next;
    });
    previewMutation.reset();
    defaultMutation.reset();
  };
  const runPreview = () => {
    const command = draftCommand(draft);
    setPreview(undefined);
    defaultMutation.reset();
    previewMutation.mutate({
      command,
      revision: draftRevision.current,
    });
  };
  const runSetDefault = () => {
    defaultMutation.mutate({
      command: draftCommand(draft),
      reviewed: preview,
      revision: draftRevision.current,
      operatorName: operator.trim(),
      auditNote: note.trim(),
    });
  };

  return (
    <section className="config-draft-editor" aria-labelledby="draft-editor-title">
      <header className="config-draft-heading">
        <span aria-hidden="true">
          <Pencil size={18} />
        </span>
        <div>
          <p className="eyebrow">Transient browser draft</p>
          <h3 id="draft-editor-title">Edit default parameters</h3>
          <p>
            Based on the current default, {seed.entry.id}. Preview changes when you want to inspect
            the complete candidate before saving it.
          </p>
        </div>
        <button
          className={iconButton}
          type="button"
          onClick={onCancel}
          aria-label="Discard parameter draft"
        >
          <X size={17} />
        </button>
      </header>

      {stale && (
        <div className="config-error" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>
            The default configuration changed. Discard this stale draft and start again from the new
            default.
          </span>
        </div>
      )}

      <div className="config-draft-layout">
        <aside className="config-draft-index" aria-label="Editable parameters">
          {definitions.map((definition) => (
            <button
              key={definition.id}
              type="button"
              className={selectedDefinition?.id === definition.id ? "selected" : undefined}
              onClick={() => {
                if (definition.id === selectedDefinition?.id) return;
                setSelectedId(definition.id);
                setInvalidFields(new Set());
              }}
            >
              <span>
                <strong>{definition.id}</strong>
                <small>{definition.value_type.shape}</small>
              </span>
              {editedValues[definition.id] && (
                <span className="draft-edited-dot" aria-label="Edited" />
              )}
            </button>
          ))}
        </aside>
        <div className="config-draft-detail">
          {selectedDefinition && selectedValue ? (
            <>
              <header>
                <div>
                  <span className="parameter-shape">{selectedDefinition.value_type.shape}</span>
                  <h4>{selectedDefinition.id}</h4>
                  <p>{selectedDefinition.description ?? "No parameter description."}</p>
                </div>
                {editedValues[selectedDefinition.id] && (
                  <button
                    className={secondaryButton}
                    type="button"
                    onClick={() => resetParameter(selectedDefinition.id)}
                  >
                    Reset
                  </button>
                )}
              </header>
              <ParameterEditor
                key={selectedDefinition.id}
                definition={selectedDefinition}
                value={selectedValue}
                baseValue={baseValues.get(selectedDefinition.id)}
                entities={seed.config.system.topology.entities ?? []}
                onChange={changeValue}
                onFieldValidityChange={setFieldValidity}
                tableRowOrigins={tableRowOrigins[selectedDefinition.id]}
                onTableRowOriginsChange={(origins) =>
                  setTableRowOrigins((current) => ({
                    ...current,
                    [selectedDefinition.id]: origins,
                  }))
                }
              />
            </>
          ) : (
            <p className="config-draft-empty">No parameter is available.</p>
          )}
        </div>
      </div>

      <div className="config-draft-review-form">
        <label className="action-note">
          <span>Audit note</span>
          <textarea
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why are these parameters changing?"
          />
        </label>
        <div className="config-draft-actions">
          <span>
            {updates.length === 0
              ? "No changes"
              : `${updates.length} typed operation${updates.length === 1 ? "" : "s"}`}
          </span>
          <button
            className={secondaryButton}
            type="button"
            disabled={
              stale ||
              invalidFields.size > 0 ||
              updates.length === 0 ||
              previewMutation.isPending ||
              saving
            }
            onClick={runPreview}
          >
            {previewMutation.isPending ? (
              <LoaderCircle className="animate-spin" size={15} />
            ) : (
              <Eye size={15} />
            )}
            Preview changes
          </button>
          <button
            className={primaryButton}
            type="button"
            disabled={
              stale ||
              invalidFields.size > 0 ||
              updates.length === 0 ||
              !operator.trim() ||
              previewMutation.isPending ||
              saving
            }
            onClick={runSetDefault}
          >
            {defaultMutation.isPending ? (
              <LoaderCircle className="animate-spin" size={15} />
            ) : (
              <CheckCircle2 size={15} />
            )}
            Set as default
          </button>
        </div>
      </div>

      {(previewMutation.error || defaultMutation.error) && (
        <div className="config-error" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>{draftErrorMessage(defaultMutation.error ?? previewMutation.error)}</span>
        </div>
      )}

      {preview && <DraftPreview preview={preview} base={seed.config} />}
    </section>
  );
}

function defaultDraftEntryId(candidateId: string, contentHash: string): string {
  const normalized =
    candidateId
      .trim()
      .replace(/[^A-Za-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "") || "config";
  const digest = contentHash.includes(":")
    ? contentHash.slice(contentHash.indexOf(":") + 1)
    : contentHash;
  return `${normalized}-${digest.slice(0, 12)}`;
}

function DraftPreview({
  preview,
  base,
}: {
  preview: ConfigDraftPreview;
  base: ConfigProfileSnapshot;
}) {
  return (
    <section className="config-draft-preview" aria-labelledby="draft-preview-title">
      <header>
        <span className={preview.valid ? "preview-valid" : "preview-invalid"} aria-hidden="true">
          {preview.valid ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
        </span>
        <div>
          <h4 id="draft-preview-title">
            {preview.valid ? "Candidate is valid" : "Candidate needs changes"}
          </h4>
          <p>
            {preview.valid
              ? `${preview.deltas.length} parameter delta${
                  preview.deltas.length === 1 ? "" : "s"
                } passed daemon validation.`
              : "The daemon did not produce a registerable candidate."}
          </p>
        </div>
      </header>
      {preview.problems.length > 0 && (
        <ul className="config-draft-problems">
          {preview.problems.map((problem, index) => (
            <li key={`${problem.code}-${index}`}>
              <strong>{problem.message}</strong>
              <small>
                {problem.code}
                {problem.location ? ` · ${problemLocationLabel(problem.location)}` : ""}
              </small>
            </li>
          ))}
        </ul>
      )}
      {preview.valid && preview.config && (
        <ConfigParameters
          config={preview.config}
          activeConfig={base}
          headingId="draft-preview-parameters"
        />
      )}
    </section>
  );
}

function draftCommand(draft: PendingConfigDraft): ConfigDraftCommand {
  const [first, ...rest] = draft.updates;
  if (!first) throw new Error("A config draft requires at least one update.");
  return { ...draft, updates: [first, ...rest] };
}

function problemLocationLabel(
  location: NonNullable<ConfigDraftPreview["problems"][number]["location"]>,
): string {
  const prefix = "root" in location ? location.root : location.kind;
  return "path" in location && location.path.length > 0
    ? `${prefix}.${location.path.join(".")}`
    : prefix;
}

function draftErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "The default configuration changed before the daemon could apply this draft. Discard it and start again.";
  }
  return error instanceof Error ? error.message : "The request failed.";
}
