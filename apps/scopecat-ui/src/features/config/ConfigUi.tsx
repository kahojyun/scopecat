import { CircleDot } from "lucide-react";
import type { ReactNode } from "react";

export function ActionNote({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="action-note">
      <span>Audit note</span>
      <textarea
        rows={2}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Why is this configuration changing?"
      />
    </label>
  );
}

export function ConfigFact({
  label,
  value,
  code = false,
}: {
  label: string;
  value: string;
  code?: boolean;
}) {
  return (
    <div className="config-fact">
      <span>{label}</span>
      {code ? <code title={value}>{value}</code> : <strong>{value}</strong>}
    </div>
  );
}

export function ConfigInlineEmpty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="config-inline-empty">
      <CircleDot size={16} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
    </div>
  );
}

export function ConfigBoundaryMessage({
  icon,
  title,
  detail,
  warning = false,
  compact = false,
  action,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  warning?: boolean;
  compact?: boolean;
  action?: ReactNode;
}) {
  return (
    <section className={`config-boundary${warning ? " warning" : ""}${compact ? " compact" : ""}`}>
      <span aria-hidden="true">{icon}</span>
      <h2>{title}</h2>
      <p>{detail}</p>
      {action}
    </section>
  );
}
