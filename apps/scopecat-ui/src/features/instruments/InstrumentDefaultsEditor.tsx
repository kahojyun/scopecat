import { useEffect, useState } from "react";
import type {
  InstrumentComponent,
  InstrumentDescription,
  InstrumentInterface,
  InstrumentProperty,
  InstrumentPropertyState,
  InstrumentSpec,
} from "../../api-contract";
import { titleCase } from "../../lib/presentation";
import { classes } from "../../ui/styles";
import { InstrumentPropertyInput, type InstrumentPropertyDraft } from "./InstrumentPropertyInput";

type RunStartPolicy = InstrumentSpec["run_start"];
type InterfaceMember = Pick<InstrumentInterface, "label" | "properties" | "components">;

export function InstrumentDefaultsEditor({
  description,
  defaultState,
  runStart,
  onDefaultStateChange,
  onRunStartChange,
  onValidityChange,
}: {
  description?: InstrumentDescription;
  defaultState: InstrumentPropertyState[];
  runStart: RunStartPolicy;
  onDefaultStateChange: (defaultState: InstrumentPropertyState[]) => void;
  onRunStartChange: (runStart: RunStartPolicy) => void;
  onValidityChange: (valid: boolean) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, InstrumentPropertyDraft>>({});
  const invalid = Object.values(drafts).some((draft) => draft.value === undefined);

  useEffect(() => onValidityChange(!invalid), [invalid, onValidityChange]);

  const toggle = (
    interfaceId: string,
    componentPath: string[],
    property: InstrumentProperty,
    enabled: boolean,
  ) => {
    const key = propertyKey(interfaceId, componentPath, property.id);
    if (!enabled) {
      setDrafts((current) => withoutDraft(current, key));
      onDefaultStateChange(defaultState.filter((item) => defaultPropertyKey(item) !== key));
      return;
    }
    const initial = initialDraft(property);
    setDrafts((current) => ({ ...current, [key]: initial }));
    if (initial.value !== undefined) {
      onDefaultStateChange(
        replaceDefault(defaultState, {
          interface_id: interfaceId,
          component_path: componentPath,
          property_id: property.id,
          value: initial.value,
        }),
      );
    }
  };

  const edit = (
    interfaceId: string,
    componentPath: string[],
    property: InstrumentProperty,
    draft: InstrumentPropertyDraft,
  ) => {
    const key = propertyKey(interfaceId, componentPath, property.id);
    setDrafts((current) => ({ ...current, [key]: draft }));
    if (draft.value === undefined) return;
    onDefaultStateChange(
      replaceDefault(defaultState, {
        interface_id: interfaceId,
        component_path: componentPath,
        property_id: property.id,
        value: draft.value,
      }),
    );
  };

  return (
    <section className="grid gap-2.5 border-y border-line py-3">
      <header className="flex items-end justify-between gap-3.5 max-[460px]:flex-col max-[460px]:items-stretch">
        <div className="grid gap-[3px]">
          <strong className="text-[0.66rem] text-text-soft">Experiment start</strong>
          <small className="text-[0.56rem] leading-normal text-text-dim">
            Synchronize first, then optionally apply this sparse default state.
          </small>
        </div>
        <label className="grid min-w-[210px] gap-[5px] max-[460px]:min-w-0">
          <span className="text-[0.53rem] font-extrabold tracking-[0.07em] text-text-dim uppercase">
            Start policy
          </span>
          <select
            className="min-h-[34px] w-full min-w-0 rounded-sm border border-line bg-bg px-[9px] text-[0.64rem] text-text outline-0 focus:border-accent"
            value={runStart}
            onChange={(event) => onRunStartChange(event.target.value as RunStartPolicy)}
          >
            <option value="preserve">Preserve observed state</option>
            <option value="apply_default_state">Apply configured defaults</option>
          </select>
        </label>
      </header>

      {description ? (
        <div className="grid max-h-[330px] gap-2.5 overflow-auto pr-[3px] [scrollbar-color:#344252_transparent] [scrollbar-width:thin]">
          {(description.interfaces ?? []).map((instrumentInterface) => (
            <DefaultScope
              key={instrumentInterface.id}
              interfaceId={instrumentInterface.id}
              componentPath={[]}
              member={instrumentInterface}
              defaultState={defaultState}
              drafts={drafts}
              onToggle={toggle}
              onEdit={edit}
            />
          ))}
        </div>
      ) : (
        <p className={defaultsUnavailable}>
          Test the connection to load interface-derived default settings.
          {defaultState.length > 0 &&
            ` ${defaultState.length} existing ${
              defaultState.length === 1 ? "value is" : "values are"
            } preserved.`}
        </p>
      )}

      {runStart === "apply_default_state" && defaultState.length === 0 && (
        <p className={configNote} role="status">
          Select at least one default value before enabling automatic apply.
        </p>
      )}
    </section>
  );
}

function DefaultScope({
  interfaceId,
  componentPath,
  member,
  defaultState,
  drafts,
  onToggle,
  onEdit,
}: {
  interfaceId: string;
  componentPath: string[];
  member: InterfaceMember;
  defaultState: InstrumentPropertyState[];
  drafts: Record<string, InstrumentPropertyDraft>;
  onToggle: (
    interfaceId: string,
    componentPath: string[],
    property: InstrumentProperty,
    enabled: boolean,
  ) => void;
  onEdit: (
    interfaceId: string,
    componentPath: string[],
    property: InstrumentProperty,
    draft: InstrumentPropertyDraft,
  ) => void;
}) {
  const properties = visibleDefaultProperties(member);
  const children = member.components ?? [];
  if (properties.length === 0 && children.length === 0) return null;
  const label =
    componentPath.length === 0
      ? (member.label ?? interfaceId)
      : (member.label ?? titleCase(componentPath.at(-1) ?? ""));
  return (
    <section
      className={classes(
        "grid gap-[7px]",
        componentPath.length > 0 && "border-l border-line pl-2.5",
      )}
    >
      {properties.length > 0 && (
        <>
          <h5 className="m-0 text-[0.54rem] font-extrabold tracking-[0.05em] text-text-dim uppercase">
            {label}
          </h5>
          <div className="grid gap-1.5">
            {properties.map((property) => {
              const key = propertyKey(interfaceId, componentPath, property.id);
              const assignment = defaultState.find((item) => defaultPropertyKey(item) === key);
              const enabled = assignment !== undefined || key in drafts;
              return (
                <div
                  className="grid grid-cols-[minmax(180px,1fr)_minmax(170px,0.9fr)] items-center gap-2.5 rounded-sm border border-line bg-panel-soft px-2 py-[7px] max-[680px]:grid-cols-2 max-[460px]:grid-cols-1"
                  data-testid={`instrument-default-property-${property.id}`}
                  key={property.id}
                >
                  <label className="flex min-w-0 items-center gap-2">
                    <input
                      className="min-h-[15px]! w-[15px] flex-none p-0! accent-accent"
                      type="checkbox"
                      checked={enabled}
                      aria-label={`Configure default for ${
                        property.label ?? titleCase(property.id)
                      }`}
                      onChange={(event) =>
                        onToggle(interfaceId, componentPath, property, event.target.checked)
                      }
                    />
                    <span className="grid min-w-0 gap-0.5">
                      <strong className="overflow-hidden text-[0.61rem] text-ellipsis whitespace-nowrap text-text-soft">
                        {property.label ?? titleCase(property.id)}
                      </strong>
                    </span>
                  </label>
                  <InstrumentPropertyInput
                    property={property}
                    currentValue={assignment?.value}
                    draft={drafts[key]}
                    editable={enabled}
                    ariaLabel={`${property.label ?? titleCase(property.id)} default value`}
                    onChange={(draft) => onEdit(interfaceId, componentPath, property, draft)}
                  />
                </div>
              );
            })}
          </div>
        </>
      )}
      {children.map((child: InstrumentComponent) => (
        <DefaultScope
          key={child.id}
          interfaceId={interfaceId}
          componentPath={[...componentPath, child.id]}
          member={child}
          defaultState={defaultState}
          drafts={drafts}
          onToggle={onToggle}
          onEdit={onEdit}
        />
      ))}
    </section>
  );
}

const configNote =
  "m-0 rounded-sm border border-[rgb(128_163_207_/_20%)] bg-accent-soft px-2.5 py-[9px] text-[0.58rem] leading-normal text-text-dim";
const defaultsUnavailable =
  "m-0 rounded-sm border border-dashed border-line px-2.5 py-[9px] text-[0.56rem] leading-normal text-text-dim";

function visibleDefaultProperties(member: InterfaceMember): InstrumentProperty[] {
  return (member.properties ?? []).filter((property) => property.access === "read_write");
}

function initialDraft(property: InstrumentProperty): InstrumentPropertyDraft {
  if (property.value_type.type === "bool") {
    return { raw: false, value: false };
  }
  return { raw: "" };
}

function replaceDefault(
  defaultState: InstrumentPropertyState[],
  replacement: InstrumentPropertyState,
): InstrumentPropertyState[] {
  const key = defaultPropertyKey(replacement);
  const index = defaultState.findIndex((item) => defaultPropertyKey(item) === key);
  if (index < 0) return [...defaultState, replacement];
  return defaultState.map((item, itemIndex) => (itemIndex === index ? replacement : item));
}

function withoutDraft(
  current: Record<string, InstrumentPropertyDraft>,
  removed: string,
): Record<string, InstrumentPropertyDraft> {
  return Object.fromEntries(Object.entries(current).filter(([key]) => key !== removed));
}

function defaultPropertyKey(item: InstrumentPropertyState): string {
  return propertyKey(item.interface_id, item.component_path ?? [], item.property_id);
}

function propertyKey(interfaceId: string, componentPath: string[], propertyId: string): string {
  return [interfaceId, ...componentPath, propertyId].join("\u0000");
}
