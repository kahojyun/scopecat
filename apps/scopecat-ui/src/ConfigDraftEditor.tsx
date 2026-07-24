import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  LoaderCircle,
  Pencil,
  Plus,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { ApiError } from "./api";
import { previewConfigDraft, registerConfigDraft } from "./config-api";
import {
  defaultParameterAtom,
  defaultTableRow,
  deriveConfigDraftUpdates,
} from "./config-draft";
import { ConfigParameters } from "./ConfigParameters";
import type {
  ActiveConfigState,
  ConfigDraftCommand,
  ConfigDraftPreview,
  ConfigDraftRegistrationReceipt,
  ConfigProfileSnapshot,
  ConfigRegistryEntry,
  ParameterAtom,
  ParameterDefinition,
  ParameterEntity,
  ParameterScalarType,
  StoredParameterValue,
  TableParameterType,
  TableParameterValue,
} from "./config-types";

export interface ConfigDraftSeed {
  entry: ConfigRegistryEntry;
  active: ActiveConfigState;
  config: ConfigProfileSnapshot;
}

export function ConfigDraftEditor({
  seed,
  currentActive,
  operator,
  onCancel,
  onRegistered,
}: {
  seed: ConfigDraftSeed;
  currentActive?: ActiveConfigState;
  operator: string;
  onCancel: () => void;
  onRegistered: (receipt: ConfigDraftRegistrationReceipt) => void | Promise<void>;
}) {
  const definitions = seed.config.system.parameterCatalog.definitions;
  const baseValues = useMemo(
    () =>
      new Map(
        seed.config.parameterSnapshot.values.map((value) => [value.id, value]),
      ),
    [seed.config],
  );
  const [selectedId, setSelectedId] = useState(definitions[0]?.id);
  const [editedValues, setEditedValues] = useState<
    Record<string, StoredParameterValue>
  >({});
  const [entryId, setEntryId] = useState(`${seed.entry.id}-edit`);
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<ConfigDraftPreview>();
  const [invalidFields, setInvalidFields] = useState<Set<string>>(
    () => new Set(),
  );
  const [tableRowOrigins, setTableRowOrigins] = useState<
    Record<string, Array<"base" | "new">>
  >({});
  const draftRevision = useRef(0);
  const updates = useMemo(
    () => deriveConfigDraftUpdates(seed.config, editedValues),
    [editedValues, seed.config],
  );
  const draft = useMemo<ConfigDraftCommand>(
    () => ({
      baseEntryId: seed.entry.id,
      baseContentHash: seed.active.contentHash,
      baseGeneration: seed.active.generation,
      candidateId: entryId.trim(),
      updates,
    }),
    [entryId, seed.active, seed.entry.id, updates],
  );
  const selectedDefinition = definitions.find(
    (definition) => definition.id === selectedId,
  );
  const selectedValue = selectedDefinition
    ? editedValues[selectedDefinition.id] ??
      baseValues.get(selectedDefinition.id)
    : undefined;
  const stale =
    !currentActive ||
    currentActive.entryId !== seed.active.entryId ||
    currentActive.contentHash !== seed.active.contentHash ||
    currentActive.generation !== seed.active.generation;
  const entryIdValid = entryId.trim().length > 0;

  const previewMutation = useMutation({
    mutationFn: ({
      command,
    }: {
      command: ConfigDraftCommand;
      revision: number;
    }) => previewConfigDraft(command),
    onSuccess: (result, variables) => {
      if (variables.revision === draftRevision.current) setPreview(result);
    },
  });
  const registrationMutation = useMutation({
    mutationFn: registerConfigDraft,
    onSuccess: async (receipt) => {
      await onRegistered(receipt);
    },
  });

  const changeValue = (value: StoredParameterValue) => {
    draftRevision.current += 1;
    setEditedValues((current) => ({ ...current, [value.id]: value }));
    setPreview(undefined);
    previewMutation.reset();
    registrationMutation.reset();
  };
  const setFieldValidity = useCallback((field: string, valid: boolean) => {
    draftRevision.current += 1;
    setInvalidFields((current) => {
      const next = new Set(current);
      if (valid) next.delete(field);
      else next.add(field);
      return next;
    });
    setPreview(undefined);
    previewMutation.reset();
    registrationMutation.reset();
  }, []);
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
    registrationMutation.reset();
  };
  const changeEntryId = (value: string) => {
    draftRevision.current += 1;
    setEntryId(value);
    setPreview(undefined);
    previewMutation.reset();
    registrationMutation.reset();
  };
  const runPreview = () => {
    setPreview(undefined);
    registrationMutation.reset();
    previewMutation.mutate({
      command: draft,
      revision: draftRevision.current,
    });
  };
  const runRegistration = () => {
    if (!preview?.valid || !preview.resultContentHash) return;
    registrationMutation.mutate({
      draft,
      expectedResultContentHash: preview.resultContentHash,
      entryId: entryId.trim(),
      registeredBy: operator.trim(),
      note: note.trim(),
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
          <h3 id="draft-editor-title">Edit active parameters</h3>
          <p>
            Based on {seed.entry.id} at generation {seed.active.generation}.
            Previewing validates the complete candidate in the daemon.
          </p>
        </div>
        <button
          className="icon-button"
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
            The active configuration changed. Discard this stale draft and
            start again from the new active entry.
          </span>
        </div>
      )}

      <div className="config-draft-layout">
        <aside className="config-draft-index" aria-label="Editable parameters">
          {definitions.map((definition) => (
            <button
              key={definition.id}
              type="button"
              className={
                selectedDefinition?.id === definition.id ? "selected" : undefined
              }
              onClick={() => {
                if (definition.id === selectedDefinition?.id) return;
                setSelectedId(definition.id);
                setInvalidFields(new Set());
              }}
            >
              <span>
                <strong>{definition.id}</strong>
                <small>{definition.valueType.shape}</small>
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
                  <span className="parameter-shape">
                    {selectedDefinition.valueType.shape}
                  </span>
                  <h4>{selectedDefinition.id}</h4>
                  <p>
                    {selectedDefinition.description ??
                      "No parameter description."}
                  </p>
                </div>
                {editedValues[selectedDefinition.id] && (
                  <button
                    className="secondary-button"
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
                entities={seed.config.system.topology.entities}
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
        <label>
          <span>New registry entry id</span>
          <input
            value={entryId}
            onChange={(event) => changeEntryId(event.target.value)}
            aria-invalid={!entryIdValid}
          />
          {!entryIdValid && (
            <small>Registry entry id cannot be blank.</small>
          )}
        </label>
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
              : `${updates.length} typed operation${
                  updates.length === 1 ? "" : "s"
                }`}
          </span>
          <button
            className="secondary-button"
            type="button"
            disabled={
              stale ||
              invalidFields.size > 0 ||
              !entryIdValid ||
              updates.length === 0 ||
              previewMutation.isPending ||
              registrationMutation.isPending
            }
            onClick={runPreview}
          >
            {previewMutation.isPending ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Eye size={15} />
            )}
            Preview candidate
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={
              stale ||
              invalidFields.size > 0 ||
              !preview?.valid ||
              !operator.trim() ||
              registrationMutation.isPending
            }
            onClick={runRegistration}
          >
            {registrationMutation.isPending ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Save size={15} />
            )}
            Register
          </button>
        </div>
      </div>

      {(previewMutation.error || registrationMutation.error) && (
        <div className="config-error" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>
            {draftErrorMessage(
              registrationMutation.error ?? previewMutation.error,
            )}
          </span>
        </div>
      )}

      {preview && <DraftPreview preview={preview} base={seed.config} />}
    </section>
  );
}

function ParameterEditor({
  definition,
  value,
  baseValue,
  entities,
  onChange,
  onFieldValidityChange,
  tableRowOrigins,
  onTableRowOriginsChange,
}: {
  definition: ParameterDefinition;
  value: StoredParameterValue;
  baseValue?: StoredParameterValue;
  entities: ParameterEntity[];
  onChange: (value: StoredParameterValue) => void;
  onFieldValidityChange: (field: string, valid: boolean) => void;
  tableRowOrigins?: Array<"base" | "new">;
  onTableRowOriginsChange: (origins: Array<"base" | "new">) => void;
}) {
  if (definition.valueType.shape === "series") {
    return (
      <div className="config-draft-empty">
        Series editing stays in Python for now. Scalar values and table rows
        have structured browser controls.
      </div>
    );
  }
  if (definition.valueType.shape === "scalar" && value.shape === "scalar") {
    return (
      <div className="config-scalar-editor">
        <AtomInput
          label={definition.id}
          type={definition.valueType.atom}
          value={value.value}
          entities={entities}
          onValidityChange={onFieldValidityChange}
          onChange={(next) =>
            onChange({
              id: value.id,
              shape: "scalar",
              value: next,
              metadata: value.metadata,
            })
          }
        />
      </div>
    );
  }
  if (definition.valueType.shape === "table" && value.shape === "table") {
    return (
      <TableEditor
        parameterId={definition.id}
        type={definition.valueType}
        value={value}
        baseValue={baseValue?.shape === "table" ? baseValue : undefined}
        entities={entities}
        onChange={onChange}
        onFieldValidityChange={onFieldValidityChange}
        rowOrigins={tableRowOrigins}
        onRowOriginsChange={onTableRowOriginsChange}
      />
    );
  }
  return (
    <div className="config-draft-empty">
      The stored value does not match its catalog shape.
    </div>
  );
}

function TableEditor({
  parameterId,
  type,
  value,
  baseValue,
  entities,
  onChange,
  onFieldValidityChange,
  rowOrigins,
  onRowOriginsChange,
}: {
  parameterId: string;
  type: TableParameterType;
  value: TableParameterValue;
  baseValue?: TableParameterValue;
  entities: ParameterEntity[];
  onChange: (value: StoredParameterValue) => void;
  onFieldValidityChange: (field: string, valid: boolean) => void;
  rowOrigins?: Array<"base" | "new">;
  onRowOriginsChange: (origins: Array<"base" | "new">) => void;
}) {
  const origins =
    rowOrigins ??
    value.rows.map((_, index) =>
      index < (baseValue?.rows.length ?? 0) ? "base" : "new",
    );
  const setRows = (rows: Array<Record<string, ParameterAtom>>) =>
    onChange({
      id: value.id,
      shape: "table",
      rows,
      rowLocations: [],
      metadata: value.metadata,
    });
  const updateCell = (
    rowIndex: number,
    columnId: string,
    next: ParameterAtom,
  ) => {
    setRows(
      value.rows.map((row, index) =>
        index === rowIndex ? { ...row, [columnId]: next } : row,
      ),
    );
  };
  const addRow = () => {
    setRows([...value.rows, defaultTableRow(type, entities)]);
    onRowOriginsChange([...origins, "new"]);
  };
  const deleteRow = (rowIndex: number) => {
    setRows(value.rows.filter((_, index) => index !== rowIndex));
    onRowOriginsChange(origins.filter((_, index) => index !== rowIndex));
  };
  return (
    <div className="config-table-editor">
      {type.primaryKey.length === 0 && (
        <div className="parameter-diff-note">
          This table has no primary key. The daemon will validate it as one
          complete replacement.
        </div>
      )}
      <div className="parameter-table-scroll">
        <table>
          <thead>
            <tr>
              {type.columns.map((column) => (
                <th key={column.id}>
                  <span>{column.id}</span>
                  <small>
                    {column.valueType.type}
                    {type.primaryKey.includes(column.id) ? " · key" : ""}
                  </small>
                </th>
              ))}
              <th>
                <span>Row</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {value.rows.map((row, rowIndex) => {
              const existing = origins[rowIndex] === "base";
              return (
                <tr key={rowIndex}>
                  {type.columns.map((column) => (
                    <td key={column.id}>
                      <AtomInput
                        label={`${parameterId} row ${rowIndex + 1} ${column.id}`}
                        type={column.valueType}
                        value={row[column.id] ?? null}
                        entities={entities}
                        disabled={
                          existing && type.primaryKey.includes(column.id)
                        }
                        onValidityChange={onFieldValidityChange}
                        onChange={(next) =>
                          updateCell(rowIndex, column.id, next)
                        }
                      />
                    </td>
                  ))}
                  <td>
                    <button
                      className="icon-button"
                      type="button"
                      disabled={value.rows.length <= type.minRows}
                      onClick={() => deleteRow(rowIndex)}
                      aria-label={`Delete ${parameterId} row ${rowIndex + 1}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button
        className="secondary-button"
        type="button"
        disabled={
          type.maxRows !== undefined && value.rows.length >= type.maxRows
        }
        onClick={addRow}
      >
        <Plus size={15} />
        Add row
      </button>
    </div>
  );
}

function AtomInput({
  label,
  type,
  value,
  entities,
  disabled = false,
  onChange,
  onValidityChange,
}: {
  label: string;
  type: ParameterScalarType;
  value: ParameterAtom;
  entities: ParameterEntity[];
  disabled?: boolean;
  onChange: (value: ParameterAtom) => void;
  onValidityChange: (field: string, valid: boolean) => void;
}) {
  const isNull = value === null;
  const concrete = (isNull
    ? defaultParameterAtom({ ...type, nullable: false }, entities)
    : value) as Exclude<ParameterAtom, null>;
  return (
    <div className="parameter-atom-input">
      {type.nullable && (
        <label className="parameter-null-toggle">
          <input
            type="checkbox"
            checked={isNull}
            disabled={disabled}
            onChange={(event) => {
              onValidityChange(
                type.type === "quantity" ? `${label} value` : label,
                true,
              );
              onChange(
                event.target.checked
                  ? null
                  : defaultParameterAtom(
                      { ...type, nullable: false },
                      entities,
                    ),
              );
            }}
          />
          Null
        </label>
      )}
      {!isNull && (
        <ConcreteAtomInput
          label={label}
          type={type}
          value={concrete}
          entities={entities}
          disabled={disabled}
          onChange={onChange}
          onValidityChange={onValidityChange}
        />
      )}
    </div>
  );
}

function ConcreteAtomInput({
  label,
  type,
  value,
  entities,
  disabled,
  onChange,
  onValidityChange,
}: {
  label: string;
  type: ParameterScalarType;
  value: Exclude<ParameterAtom, null>;
  entities: ParameterEntity[];
  disabled: boolean;
  onChange: (value: ParameterAtom) => void;
  onValidityChange: (field: string, valid: boolean) => void;
}) {
  if (type.type === "bool") {
    return (
      <select
        aria-label={label}
        value={value === true ? "true" : "false"}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value === "true")}
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  if (type.type === "int" || type.type === "float") {
    return (
      <NumericInput
        label={label}
        value={typeof value === "number" ? value : 0}
        integer={type.type === "int"}
        minimum={type.minimum}
        maximum={type.maximum}
        disabled={disabled}
        onChange={onChange}
        onValidityChange={onValidityChange}
      />
    );
  }
  if (type.type === "string") {
    if (type.choices) {
      return (
        <select
          aria-label={label}
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        >
          {type.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        aria-label={label}
        type="text"
        value={typeof value === "string" ? value : ""}
        minLength={type.minLength}
        maxLength={type.maxLength}
        pattern={type.pattern}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  if (type.type === "quantity") {
    const quantity =
      typeof value === "object" && "value" in value
        ? value
        : { value: 0, unit: type.unit ?? "" };
    return (
      <span className="quantity-input">
        <NumericInput
          label={`${label} value`}
          value={quantity.value}
          minimum={type.minimum}
          maximum={type.maximum}
          disabled={disabled}
          onChange={(next) =>
            onChange({ value: next, unit: quantity.unit })
          }
          onValidityChange={onValidityChange}
        />
        <input
          aria-label={`${label} unit`}
          type="text"
          value={quantity.unit}
          readOnly={type.unit !== undefined}
          disabled={disabled}
          onChange={(event) =>
            onChange({ value: quantity.value, unit: event.target.value })
          }
        />
      </span>
    );
  }
  const choices = entities.filter(
    (entity) => !type.entityKind || entity.kind === type.entityKind,
  );
  const entity =
    typeof value === "object" && "id" in value
      ? value
      : { id: "", metadata: {} };
  const selected = entityKey(entity);
  return (
    <select
      aria-label={label}
      value={selected}
      disabled={disabled}
      onChange={(event) => {
        const next = choices.find(
          (candidate) => entityKey(candidate) === event.target.value,
        );
        if (next) onChange(next);
      }}
    >
      {!choices.some((choice) => entityKey(choice) === selected) && (
        <option value={selected}>{entity.id || "Choose entity"}</option>
      )}
      {choices.map((choice) => (
        <option key={entityKey(choice)} value={entityKey(choice)}>
          {choice.id}
          {choice.kind ? ` · ${choice.kind}` : ""}
        </option>
      ))}
    </select>
  );
}

function NumericInput({
  label,
  value,
  integer = false,
  minimum,
  maximum,
  disabled,
  onChange,
  onValidityChange,
}: {
  label: string;
  value: number;
  integer?: boolean;
  minimum?: number;
  maximum?: number;
  disabled: boolean;
  onChange: (value: number) => void;
  onValidityChange: (field: string, valid: boolean) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const valid = numericTextIsValid(text, {
    integer,
    minimum,
    maximum,
  });
  return (
    <input
      aria-label={label}
      aria-invalid={!valid}
      type="number"
      value={text}
      step={integer ? 1 : "any"}
      min={minimum}
      max={maximum}
      required
      disabled={disabled}
      onChange={(event) => {
        const nextText = event.target.value;
        setText(nextText);
        const next = Number(nextText);
        const nextValid = numericTextIsValid(nextText, {
          integer,
          minimum,
          maximum,
        });
        onValidityChange(label, nextValid);
        if (nextValid) {
          onChange(next);
        }
      }}
    />
  );
}

function numericTextIsValid(
  text: string,
  {
    integer,
    minimum,
    maximum,
  }: {
    integer: boolean;
    minimum?: number;
    maximum?: number;
  },
): boolean {
  const value = Number(text);
  return (
    text !== "" &&
    Number.isFinite(value) &&
    (!integer || Number.isInteger(value)) &&
    (minimum === undefined || value >= minimum) &&
    (maximum === undefined || value <= maximum)
  );
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
        <span
          className={preview.valid ? "preview-valid" : "preview-invalid"}
          aria-hidden="true"
        >
          {preview.valid ? (
            <CheckCircle2 size={17} />
          ) : (
            <AlertTriangle size={17} />
          )}
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
                {problem.location
                  ? ` · ${problem.location.root ?? problem.location.kind}${
                      problem.location.path.length
                        ? `.${problem.location.path.join(".")}`
                        : ""
                    }`
                  : ""}
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

function entityKey(entity: ParameterEntity): string {
  return JSON.stringify([entity.kind ?? null, entity.id]);
}

function draftErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "The active configuration changed before the daemon could apply this draft. Discard it and start again.";
  }
  return error instanceof Error ? error.message : "The request failed.";
}
