import { useEffect, useMemo, useState } from "react";
import type {
  InstrumentComponent,
  InstrumentDescription,
  InstrumentInterface,
  InstrumentProperty,
  InstrumentPropertyState,
  InstrumentSpec,
  InstrumentStateValue,
} from "../../api-contract";
import { titleCase } from "../../lib/presentation";
import { InstrumentPropertyInput, type InstrumentPropertyDraft } from "./InstrumentPropertyInput";

type RunStartPolicy = InstrumentSpec["run_start"];
type InterfaceMember = Pick<InstrumentInterface, "label" | "properties" | "state" | "components">;

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
  const requiredMissing = useMemo(
    () => missingRequiredDefaults(description, defaultState),
    [defaultState, description],
  );
  const invalid =
    Object.values(drafts).some((draft) => draft.value === undefined) || requiredMissing.length > 0;

  useEffect(() => onValidityChange(!invalid), [invalid, onValidityChange]);

  const toggle = (
    interfaceId: string,
    componentPath: string[],
    member: InterfaceMember,
    property: InstrumentProperty,
    enabled: boolean,
  ) => {
    const key = propertyKey(interfaceId, componentPath, property.id);
    if (!enabled) {
      const removedKeys = keysRemovedWithProperty(interfaceId, componentPath, member, property.id);
      setDrafts((current) => withoutDrafts(current, removedKeys));
      onDefaultStateChange(
        defaultState.filter((item) => !removedKeys.has(defaultPropertyKey(item))),
      );
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
    member: InterfaceMember,
    property: InstrumentProperty,
    draft: InstrumentPropertyDraft,
  ) => {
    const key = propertyKey(interfaceId, componentPath, property.id);
    setDrafts((current) => ({ ...current, [key]: draft }));
    if (draft.value === undefined) return;
    let next = replaceDefault(defaultState, {
      interface_id: interfaceId,
      component_path: componentPath,
      property_id: property.id,
      value: draft.value,
    });
    if (member.state?.discriminator_property_id === property.id) {
      const keep = keysForSelectedCase(interfaceId, componentPath, member, draft.value);
      next = next.filter(
        (item) =>
          !sameScope(item, interfaceId, componentPath) ||
          !casePropertyIds(member).has(item.property_id) ||
          keep.has(defaultPropertyKey(item)),
      );
      setDrafts((current) => filterCaseDrafts(current, interfaceId, componentPath, member, keep));
    }
    onDefaultStateChange(next);
  };

  return (
    <section className="instrument-defaults-editor">
      <header>
        <div>
          <strong>Experiment start</strong>
          <small>Synchronize first, then optionally apply this sparse default state.</small>
        </div>
        <label>
          <span>Start policy</span>
          <select
            value={runStart}
            onChange={(event) => onRunStartChange(event.target.value as RunStartPolicy)}
          >
            <option value="preserve">Preserve observed state</option>
            <option value="apply_default_state">Apply configured defaults</option>
          </select>
        </label>
      </header>

      {description ? (
        <div className="instrument-default-scopes">
          {(description.interfaces ?? []).map((instrumentInterface) => (
            <DefaultScope
              key={instrumentInterface.id}
              interfaceId={instrumentInterface.id}
              componentPath={[]}
              member={instrumentInterface}
              defaultState={defaultState}
              drafts={drafts}
              requiredMissing={new Set(requiredMissing)}
              onToggle={toggle}
              onEdit={edit}
            />
          ))}
        </div>
      ) : (
        <p className="instrument-defaults-unavailable">
          Test the connection to load interface-derived default settings.
          {defaultState.length > 0 &&
            ` ${defaultState.length} existing ${
              defaultState.length === 1 ? "value is" : "values are"
            } preserved.`}
        </p>
      )}

      {runStart === "apply_default_state" && defaultState.length === 0 && (
        <p className="instrument-config-note" role="status">
          Select at least one default value before enabling automatic apply.
        </p>
      )}
      {requiredMissing.length > 0 && (
        <p className="instrument-config-note" role="status">
          The selected mode requires: {requiredMissing.map(propertyLabelFromKey).join(", ")}.
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
  requiredMissing,
  onToggle,
  onEdit,
}: {
  interfaceId: string;
  componentPath: string[];
  member: InterfaceMember;
  defaultState: InstrumentPropertyState[];
  drafts: Record<string, InstrumentPropertyDraft>;
  requiredMissing: Set<string>;
  onToggle: (
    interfaceId: string,
    componentPath: string[],
    member: InterfaceMember,
    property: InstrumentProperty,
    enabled: boolean,
  ) => void;
  onEdit: (
    interfaceId: string,
    componentPath: string[],
    member: InterfaceMember,
    property: InstrumentProperty,
    draft: InstrumentPropertyDraft,
  ) => void;
}) {
  const properties = visibleDefaultProperties(interfaceId, componentPath, member, defaultState);
  const children = member.components ?? [];
  if (properties.length === 0 && children.length === 0) return null;
  const label =
    componentPath.length === 0
      ? (member.label ?? interfaceId)
      : (member.label ?? titleCase(componentPath.at(-1) ?? ""));
  return (
    <section className="instrument-default-scope">
      {properties.length > 0 && (
        <>
          <h5>{label}</h5>
          <div className="instrument-default-properties">
            {properties.map((property) => {
              const key = propertyKey(interfaceId, componentPath, property.id);
              const assignment = defaultState.find((item) => defaultPropertyKey(item) === key);
              const enabled = assignment !== undefined || key in drafts;
              return (
                <div className="instrument-default-property" key={property.id}>
                  <label className="instrument-default-toggle">
                    <input
                      type="checkbox"
                      checked={enabled}
                      aria-label={`Configure default for ${
                        property.label ?? titleCase(property.id)
                      }`}
                      onChange={(event) =>
                        onToggle(interfaceId, componentPath, member, property, event.target.checked)
                      }
                    />
                    <span>
                      <strong>{property.label ?? titleCase(property.id)}</strong>
                      {requiredMissing.has(key) && <small>Required for selected mode</small>}
                    </span>
                  </label>
                  <InstrumentPropertyInput
                    property={property}
                    currentValue={assignment?.value}
                    draft={drafts[key]}
                    editable={enabled}
                    ariaLabel={`${property.label ?? titleCase(property.id)} default value`}
                    onChange={(draft) =>
                      onEdit(interfaceId, componentPath, member, property, draft)
                    }
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
          requiredMissing={requiredMissing}
          onToggle={onToggle}
          onEdit={onEdit}
        />
      ))}
    </section>
  );
}

function visibleDefaultProperties(
  interfaceId: string,
  componentPath: string[],
  member: InterfaceMember,
  defaultState: InstrumentPropertyState[],
): InstrumentProperty[] {
  const writable = new Map(
    (member.properties ?? [])
      .filter((property) => property.access === "read_write")
      .map((property) => [property.id, property]),
  );
  if (!member.state) return [...writable.values()];
  const discriminatorId = member.state.discriminator_property_id;
  const discriminator = defaultValue(defaultState, interfaceId, componentPath, discriminatorId);
  const selectedCase =
    typeof discriminator === "string"
      ? member.state.cases.find((candidate) => candidate.value === discriminator)
      : undefined;
  const ids = [
    discriminatorId,
    ...(member.state.common_property_ids ?? []),
    ...(selectedCase?.property_ids ?? []),
  ];
  return ids.flatMap((id) => {
    const property = writable.get(id);
    return property ? [property] : [];
  });
}

function missingRequiredDefaults(
  description: InstrumentDescription | undefined,
  defaultState: InstrumentPropertyState[],
): string[] {
  if (!description) return [];
  const missing: string[] = [];
  const walk = (interfaceId: string, componentPath: string[], member: InterfaceMember) => {
    const state = member.state;
    if (state) {
      const discriminator = defaultValue(
        defaultState,
        interfaceId,
        componentPath,
        state.discriminator_property_id,
      );
      const selectedCase =
        typeof discriminator === "string"
          ? state.cases.find((candidate) => candidate.value === discriminator)
          : undefined;
      for (const propertyId of selectedCase?.required_on_entry_property_ids ?? []) {
        if (defaultValue(defaultState, interfaceId, componentPath, propertyId) === undefined) {
          missing.push(propertyKey(interfaceId, componentPath, propertyId));
        }
      }
    }
    for (const child of member.components ?? []) {
      walk(interfaceId, [...componentPath, child.id], child);
    }
  };
  for (const instrumentInterface of description.interfaces ?? []) {
    walk(instrumentInterface.id, [], instrumentInterface);
  }
  return missing;
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

function keysRemovedWithProperty(
  interfaceId: string,
  componentPath: string[],
  member: InterfaceMember,
  propertyId: string,
): Set<string> {
  const keys = new Set([propertyKey(interfaceId, componentPath, propertyId)]);
  if (member.state?.discriminator_property_id === propertyId) {
    for (const casePropertyId of casePropertyIds(member)) {
      keys.add(propertyKey(interfaceId, componentPath, casePropertyId));
    }
  }
  return keys;
}

function keysForSelectedCase(
  interfaceId: string,
  componentPath: string[],
  member: InterfaceMember,
  value: InstrumentStateValue,
): Set<string> {
  if (typeof value !== "string" || !member.state) return new Set();
  const selectedCase = member.state.cases.find((candidate) => candidate.value === value);
  return new Set(
    (selectedCase?.property_ids ?? []).map((propertyId) =>
      propertyKey(interfaceId, componentPath, propertyId),
    ),
  );
}

function casePropertyIds(member: InterfaceMember): Set<string> {
  return new Set((member.state?.cases ?? []).flatMap((stateCase) => stateCase.property_ids ?? []));
}

function caseKeys(
  interfaceId: string,
  componentPath: string[],
  member: InterfaceMember,
): Set<string> {
  return new Set(
    [...casePropertyIds(member)].map((propertyId) =>
      propertyKey(interfaceId, componentPath, propertyId),
    ),
  );
}

function filterCaseDrafts(
  drafts: Record<string, InstrumentPropertyDraft>,
  interfaceId: string,
  componentPath: string[],
  member: InterfaceMember,
  keep: Set<string>,
): Record<string, InstrumentPropertyDraft> {
  const scopedCaseKeys = caseKeys(interfaceId, componentPath, member);
  return Object.fromEntries(
    Object.entries(drafts).filter(([key]) => !scopedCaseKeys.has(key) || keep.has(key)),
  );
}

function withoutDrafts(
  current: Record<string, InstrumentPropertyDraft>,
  removed: Set<string>,
): Record<string, InstrumentPropertyDraft> {
  return Object.fromEntries(Object.entries(current).filter(([key]) => !removed.has(key)));
}

function defaultValue(
  defaultState: InstrumentPropertyState[],
  interfaceId: string,
  componentPath: string[],
  propertyId: string,
): InstrumentStateValue | undefined {
  return defaultState.find(
    (item) =>
      item.interface_id === interfaceId &&
      samePath(item.component_path ?? [], componentPath) &&
      item.property_id === propertyId,
  )?.value;
}

function sameScope(
  item: InstrumentPropertyState,
  interfaceId: string,
  componentPath: string[],
): boolean {
  return item.interface_id === interfaceId && samePath(item.component_path ?? [], componentPath);
}

function samePath(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function defaultPropertyKey(item: InstrumentPropertyState): string {
  return propertyKey(item.interface_id, item.component_path ?? [], item.property_id);
}

function propertyKey(interfaceId: string, componentPath: string[], propertyId: string): string {
  return [interfaceId, ...componentPath, propertyId].join("\u0000");
}

function propertyLabelFromKey(key: string): string {
  return titleCase(key.split("\u0000").at(-1) ?? key);
}
