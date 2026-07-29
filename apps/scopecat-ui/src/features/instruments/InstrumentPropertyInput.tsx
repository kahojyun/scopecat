import type { InstrumentProperty, InstrumentStateValue } from "../../api-contract";

export interface InstrumentPropertyDraft {
  raw: string | boolean;
  unit?: string;
  value?: InstrumentStateValue;
}

export function InstrumentPropertyInput({
  property,
  currentValue,
  draft,
  editable,
  ariaLabel,
  onChange,
}: {
  property: InstrumentProperty;
  currentValue?: InstrumentStateValue;
  draft?: InstrumentPropertyDraft;
  editable: boolean;
  ariaLabel?: string;
  onChange: (draft: InstrumentPropertyDraft) => void;
}) {
  const type = property.value_type;
  const value = draft?.raw ?? inputValue(currentValue, type.type);
  if (type.type === "bool") {
    return (
      <span className="boolean-editor">
        <input
          type="checkbox"
          checked={typeof value === "boolean" ? value : false}
          disabled={!editable}
          aria-label={ariaLabel}
          onChange={(event) => onChange({ raw: event.target.checked, value: event.target.checked })}
        />
        {typeof value === "boolean" ? (value ? "On" : "Off") : "Unknown"}
      </span>
    );
  }
  if (type.type === "string" && type.choices) {
    return (
      <select
        value={typeof value === "string" ? value : ""}
        disabled={!editable}
        aria-label={ariaLabel}
        onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
      >
        <option value="" disabled>
          Select…
        </option>
        {type.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    );
  }
  if (type.type === "int" || type.type === "float" || type.type === "quantity") {
    return (
      <span className="number-unit-editor">
        <input
          type="number"
          step={type.type === "int" ? 1 : "any"}
          min={type.minimum ?? undefined}
          max={type.maximum ?? undefined}
          value={typeof value === "string" || typeof value === "number" ? value : ""}
          placeholder={editable ? "Enter value" : "—"}
          disabled={!editable}
          aria-label={ariaLabel}
          aria-invalid={draft !== undefined && draft.value === undefined}
          onChange={(event) => {
            const raw = event.target.value;
            const number = Number(raw);
            const valid =
              raw.length > 0 &&
              Number.isFinite(number) &&
              (type.type !== "int" || Number.isInteger(number)) &&
              (type.minimum === null || type.minimum === undefined || number >= type.minimum) &&
              (type.maximum === null || type.maximum === undefined || number <= type.maximum);
            const unit =
              type.type === "quantity"
                ? (type.unit ?? quantityValue(currentValue)?.unit)
                : undefined;
            const typed =
              valid && type.type === "quantity" && unit
                ? { value: number, unit }
                : valid && type.type !== "quantity"
                  ? number
                  : undefined;
            onChange({ raw, value: typed });
          }}
        />
        {type.type === "quantity" && <span>{type.unit ?? "unit required"}</span>}
      </span>
    );
  }
  return (
    <input
      type="text"
      value={typeof value === "string" ? value : ""}
      placeholder={editable ? "Enter value" : "—"}
      disabled={!editable}
      aria-label={ariaLabel}
      onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
    />
  );
}

function inputValue(
  value: InstrumentStateValue | undefined,
  type: InstrumentProperty["value_type"]["type"],
): string | number | boolean {
  if (value === undefined) return "";
  if (type === "quantity") return quantityValue(value)?.value ?? "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  return "";
}

function quantityValue(
  value: InstrumentStateValue | undefined,
): { value: number; unit: string } | undefined {
  if (
    typeof value === "object" &&
    value !== null &&
    "value" in value &&
    "unit" in value &&
    typeof value.value === "number" &&
    typeof value.unit === "string"
  ) {
    return value;
  }
  return undefined;
}
