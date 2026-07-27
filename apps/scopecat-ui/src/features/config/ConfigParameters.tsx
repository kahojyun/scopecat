import { useEffect, useMemo, useState } from "react";
import { Braces, CircleDot, GitCompareArrows, Search, Table2 } from "lucide-react";
import {
  diffConfigParameters,
  parameterAtomLabel,
  parameterTypeLabel,
  type ParameterDiff,
  type TableRowDiff,
} from "./config-diff";
import type {
  ConfigProfileSnapshot,
  ParameterAtom,
  ParameterDefinition,
  StoredParameterValue,
  TableParameterType,
  TableParameterValue,
} from "../../api-contract";

export function ConfigParameters({
  config,
  activeConfig,
  headingId = "parameters-heading",
}: {
  config: ConfigProfileSnapshot;
  activeConfig?: ConfigProfileSnapshot;
  headingId?: string;
}) {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const diffs = useMemo(
    () => diffConfigParameters(activeConfig ?? config, config),
    [activeConfig, config],
  );
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    if (!query) return diffs;
    return diffs.filter((diff) => {
      const definition = diff.afterDefinition ?? diff.beforeDefinition;
      return [diff.parameterId, definition?.description, definition?.value_type.shape]
        .filter((value): value is string => value !== undefined)
        .join(" ")
        .toLocaleLowerCase()
        .includes(query);
    });
  }, [diffs, search]);
  const selected = filtered.find((diff) => diff.parameterId === selectedId) ?? filtered[0];
  const changedCount = diffs.filter((diff) => diff.status !== "unchanged").length;

  useEffect(() => {
    if (selected && selected.parameterId !== selectedId) {
      setSelectedId(selected.parameterId);
    }
  }, [selected, selectedId]);

  return (
    <section className="config-parameters" aria-labelledby={headingId}>
      <header className="parameter-browser-heading">
        <div>
          <span className="parameter-heading-icon" aria-hidden="true">
            <Table2 size={17} />
          </span>
          <span>
            <h4 id={headingId}>Parameters</h4>
            <small>{config.system.parameter_catalog.id}</small>
          </span>
        </div>
        {activeConfig && (
          <span
            className={
              changedCount === 0 ? "parameter-compare-badge" : "parameter-compare-badge changed"
            }
          >
            <GitCompareArrows size={13} aria-hidden="true" />
            {changedCount === 0 ? "Matches default" : `${changedCount} changed`}
          </span>
        )}
      </header>

      <div className="parameter-browser-layout">
        <aside className="parameter-index" aria-label="Parameters">
          <label className="parameter-search">
            <Search size={14} aria-hidden="true" />
            <span className="visually-hidden">Find parameter</span>
            <input
              type="search"
              value={search}
              placeholder="Find parameter"
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <div className="parameter-index-list">
            {filtered.length === 0 ? (
              <ParameterEmpty
                title="No matching parameters"
                detail="Try a parameter id, description, or shape."
              />
            ) : (
              filtered.map((diff) => {
                const definition = diff.afterDefinition ?? diff.beforeDefinition;
                return (
                  <button
                    key={diff.parameterId}
                    type="button"
                    className={
                      diff.parameterId === selected?.parameterId
                        ? "parameter-index-item selected"
                        : "parameter-index-item"
                    }
                    onClick={() => setSelectedId(diff.parameterId)}
                    aria-current={diff.parameterId === selected?.parameterId ? "true" : undefined}
                  >
                    <span>
                      <strong>{diff.parameterId}</strong>
                      <small>{parameterTypeLabel(definition)}</small>
                    </span>
                    {diff.status !== "unchanged" && <DiffBadge status={diff.status} />}
                  </button>
                );
              })
            )}
          </div>
        </aside>

        <div className="parameter-detail">
          {selected ? (
            <ParameterDetail diff={selected} comparing={activeConfig !== undefined} />
          ) : (
            <ParameterEmpty
              title="Nothing selected"
              detail="Choose a parameter to inspect its typed value."
            />
          )}
        </div>
      </div>

      <details className="raw-config">
        <summary>
          <Braces size={15} aria-hidden="true" />
          Advanced · raw snapshot
        </summary>
        <pre>{JSON.stringify(config, null, 2)}</pre>
      </details>
    </section>
  );
}

function ParameterDetail({ diff, comparing }: { diff: ParameterDiff; comparing: boolean }) {
  const definition = diff.afterDefinition ?? diff.beforeDefinition;
  const value = diff.after ?? diff.before;
  if (!definition || !value) {
    return (
      <ParameterEmpty
        title="Incomplete parameter"
        detail="The catalog definition and stored value are not both available."
      />
    );
  }
  return (
    <>
      <header className="parameter-detail-heading">
        <div>
          <span className="parameter-shape">{value.shape}</span>
          <h5>{diff.parameterId}</h5>
          <p>{definition.description ?? "No parameter description."}</p>
        </div>
        {comparing && <DiffBadge status={diff.status} />}
      </header>
      <div className="parameter-type-facts">
        <ParameterFact label="Type" value={parameterTypeLabel(definition)} />
        {definition.value_type.shape === "table" && (
          <>
            <ParameterFact
              label="Rows"
              value={String(value.shape === "table" ? (value.rows?.length ?? 0) : 0)}
            />
            <ParameterFact
              label="Primary key"
              value={(definition.value_type.primary_key ?? []).join(", ") || "None"}
            />
          </>
        )}
      </div>
      {diff.status === "schema-changed" && (
        <div className="parameter-diff-note warning">
          The parameter schema changed. Values are shown without a cell-level comparison.
        </div>
      )}
      <ParameterValueView diff={diff} definition={definition} value={value} />
    </>
  );
}

function ParameterValueView({
  diff,
  definition,
  value,
}: {
  diff: ParameterDiff;
  definition: ParameterDefinition;
  value: StoredParameterValue;
}) {
  if (value.shape === "scalar") {
    const before = diff.before?.shape === "scalar" ? diff.before.value : undefined;
    const after = diff.after?.shape === "scalar" ? diff.after.value : undefined;
    return (
      <div className="scalar-parameter-view">
        {diff.status !== "unchanged" && before !== undefined && after !== undefined ? (
          <ValueComparison before={before} after={after} />
        ) : (
          <ParameterAtomView value={value.value} />
        )}
      </div>
    );
  }
  const valueType = definition.value_type.shape === "table" ? definition.value_type : undefined;
  if (!valueType) {
    return (
      <ParameterEmpty
        title="Table schema unavailable"
        detail="The stored table does not have a matching catalog definition."
      />
    );
  }
  return <TableValueView diff={diff} value={value} valueType={valueType} />;
}

function ValueComparison({ before, after }: { before: ParameterAtom; after: ParameterAtom }) {
  return (
    <div className="value-comparison" aria-label="Default to selected value">
      <span>
        <small>Default</small>
        <ParameterAtomView value={before} />
      </span>
      <GitCompareArrows size={16} aria-hidden="true" />
      <span>
        <small>Selected</small>
        <ParameterAtomView value={after} />
      </span>
    </div>
  );
}

function TableValueView({
  diff,
  value,
  valueType,
}: {
  diff: ParameterDiff;
  value: TableParameterValue;
  valueType: TableParameterType;
}) {
  const keyedRows = diff.table?.mode === "keyed" ? diff.table.rows : undefined;
  const rows =
    keyedRows ??
    (value.rows ?? []).map(
      (row, index): TableRowDiff => ({
        identity: String(index),
        status: "unchanged",
        key: {},
        after: row,
        cells: valueType.columns.map(({ id }) => ({
          columnId: id,
          status: "unchanged",
          after: row[id],
        })),
      }),
    );
  return (
    <div className="table-parameter-view">
      {diff.status === "changed" && diff.table?.mode === "complete-replacement" && (
        <div className="parameter-diff-note">
          This table has no primary key, so it is compared as one complete replacement.
        </div>
      )}
      <div className="parameter-table-scroll">
        <table>
          <thead>
            <tr>
              {valueType.columns.map((column) => (
                <th key={column.id}>
                  <span>{column.id}</span>
                  <small>
                    {column.value_type.type}
                    {(valueType.primary_key ?? []).includes(column.id) ? " · key" : ""}
                  </small>
                </th>
              ))}
              {keyedRows && <th>Status</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.identity} className={row.status}>
                {valueType.columns.map((column) => {
                  const cell = row.cells.find((candidate) => candidate.columnId === column.id);
                  const displayed = row.after?.[column.id] ?? row.before?.[column.id];
                  return (
                    <td
                      key={column.id}
                      className={
                        cell && cell.status !== "unchanged" ? `cell-${cell.status}` : undefined
                      }
                    >
                      <ParameterAtomView value={displayed!} />
                      {cell?.status === "changed" && (
                        <small className="previous-cell-value">
                          was {parameterAtomLabel(cell.before)}
                        </small>
                      )}
                    </td>
                  );
                })}
                {keyedRows && (
                  <td>
                    <DiffBadge status={row.status} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ParameterAtomView({ value }: { value: ParameterAtom }) {
  return <code className="parameter-atom">{parameterAtomLabel(value)}</code>;
}

function ParameterFact({ label, value }: { label: string; value: string }) {
  return (
    <span className="parameter-fact">
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function DiffBadge({ status }: { status: ParameterDiff["status"] | TableRowDiff["status"] }) {
  const label = status.replace("-", " ");
  return <span className={`parameter-diff-badge ${status}`}>{label}</span>;
}

function ParameterEmpty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="parameter-empty">
      <CircleDot size={16} aria-hidden="true" />
      <span>
        <strong>{title}</strong>
        <p>{detail}</p>
      </span>
    </div>
  );
}
