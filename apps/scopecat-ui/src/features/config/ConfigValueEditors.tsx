import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { defaultParameterAtom, defaultTableRow } from "./config-draft";
import type {
  ParameterAtom,
  ParameterDefinition,
  ParameterEntity,
  ParameterScalarType,
  StoredParameterValue,
  TableParameterType,
  TableParameterValue,
} from "./config-types";

export function ParameterEditor({
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
        Series editing stays in Python for now. Scalar values and table rows have structured browser
        controls.
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
    <div className="config-draft-empty">The stored value does not match its catalog shape.</div>
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
    value.rows.map((_, index) => (index < (baseValue?.rows.length ?? 0) ? "base" : "new"));
  const setRows = (rows: Array<Record<string, ParameterAtom>>) =>
    onChange({
      id: value.id,
      shape: "table",
      rows,
      rowLocations: [],
      metadata: value.metadata,
    });
  const updateCell = (rowIndex: number, columnId: string, next: ParameterAtom) => {
    setRows(
      value.rows.map((row, index) => (index === rowIndex ? { ...row, [columnId]: next } : row)),
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
          This table has no primary key. The daemon will validate it as one complete replacement.
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
                        disabled={existing && type.primaryKey.includes(column.id)}
                        onValidityChange={onFieldValidityChange}
                        onChange={(next) => updateCell(rowIndex, column.id, next)}
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
        disabled={type.maxRows !== undefined && value.rows.length >= type.maxRows}
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
  const concrete = (
    isNull ? defaultParameterAtom({ ...type, nullable: false }, entities) : value
  ) as Exclude<ParameterAtom, null>;
  return (
    <div className="parameter-atom-input">
      {type.nullable && (
        <label className="parameter-null-toggle">
          <input
            type="checkbox"
            checked={isNull}
            disabled={disabled}
            onChange={(event) => {
              onValidityChange(type.type === "quantity" ? `${label} value` : label, true);
              onChange(
                event.target.checked
                  ? null
                  : defaultParameterAtom({ ...type, nullable: false }, entities),
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
      typeof value === "object" && "value" in value ? value : { value: 0, unit: type.unit ?? "" };
    return (
      <span className="quantity-input">
        <NumericInput
          label={`${label} value`}
          value={quantity.value}
          minimum={type.minimum}
          maximum={type.maximum}
          disabled={disabled}
          onChange={(next) => onChange({ value: next, unit: quantity.unit })}
          onValidityChange={onValidityChange}
        />
        <input
          aria-label={`${label} unit`}
          type="text"
          value={quantity.unit}
          readOnly={type.unit !== undefined}
          disabled={disabled}
          onChange={(event) => onChange({ value: quantity.value, unit: event.target.value })}
        />
      </span>
    );
  }
  const choices = entities.filter((entity) => !type.entityKind || entity.kind === type.entityKind);
  const entity = typeof value === "object" && "id" in value ? value : { id: "", metadata: {} };
  const selected = entityKey(entity);
  return (
    <select
      aria-label={label}
      value={selected}
      disabled={disabled}
      onChange={(event) => {
        const next = choices.find((candidate) => entityKey(candidate) === event.target.value);
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

function entityKey(entity: ParameterEntity): string {
  return JSON.stringify([entity.kind ?? null, entity.id]);
}
