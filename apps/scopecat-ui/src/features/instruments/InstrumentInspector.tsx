import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Cable,
  Check,
  CircleOff,
  Database,
  LoaderCircle,
  Pencil,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Unplug,
} from "lucide-react";
import type {
  InstrumentCapability,
  InstrumentCapabilityField,
  InstrumentCollectReceipt,
  InstrumentSessionLease,
  InstrumentState,
  InstrumentStateValue,
  InstrumentView,
} from "../../api-contract";
import { errorMessage, formatDateTime, formatRelative, titleCase } from "../../lib/presentation";
import {
  applyInstrumentState,
  collectInstrumentCapability,
  createInstrumentOperationId,
  instrumentCollectionReadiness,
  readInstrumentState,
  resolveInstrumentAttention,
  retryTransientInstrumentMutation,
  type StagedInstrumentField,
} from "./instrument-api";

interface DraftValue {
  raw: string | boolean;
  value?: InstrumentStateValue;
}

export function InstrumentInspector({
  instrument,
  lease,
  actor,
  sessionError,
  connectPending,
  closePending,
  onActorChange,
  onConnect,
  onClose,
  onLeaseLost,
  onEditConnection,
}: {
  instrument: InstrumentView;
  lease?: InstrumentSessionLease;
  actor: string;
  sessionError?: string;
  connectPending: boolean;
  closePending: boolean;
  onActorChange: (actor: string) => void;
  onConnect: () => void;
  onClose: () => void;
  onLeaseLost: (message: string, expiresAt?: string) => void;
  onEditConnection: () => void;
}) {
  const queryClient = useQueryClient();
  const instrumentId = instrument.spec.id;
  const connected = lease?.instrument_ids.includes(instrumentId) ?? false;
  const connectionEditable = instrument.spec.connection.kind === "tcpip_socket";
  const interactionEnabled = connected && !closePending;
  const description =
    lease?.descriptions.find((candidate) => candidate.instrument_id === instrumentId) ??
    instrument.description ??
    undefined;
  const [state, setState] = useState<InstrumentState>();
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const [applyResult, setApplyResult] = useState<string>();
  const [collectResults, setCollectResults] = useState<Record<string, InstrumentCollectReceipt>>(
    {},
  );
  const applyOperationIdRef = useRef<string | undefined>(undefined);
  const collectOperationIdsRef = useRef<Record<string, string>>({});

  useEffect(() => {
    if (connected) return;
    applyOperationIdRef.current = undefined;
    collectOperationIdsRef.current = {};
    setState(undefined);
    setDrafts({});
    setApplyResult(undefined);
    setCollectResults({});
  }, [connected]);

  const readMutation = useMutation({
    mutationFn: () => readInstrumentState(requireLease(lease), instrumentId),
    onSuccess: (snapshot) => {
      applyOperationIdRef.current = undefined;
      collectOperationIdsRef.current = {};
      setState(snapshot);
      setDrafts({});
      setApplyResult(undefined);
      setCollectResults({});
    },
  });
  useEffect(() => {
    if (connected && lease) readMutation.mutate();
    // A heartbeat returns a new lease object; only a newly opened session should auto-read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, instrumentId, lease?.session_id]);
  const stagedFields = useMemo(() => stagedInstrumentFields(drafts), [drafts]);
  const invalidDraft = Object.values(drafts).some((draft) => draft.value === undefined);
  const applyMutation = useMutation({
    mutationFn: ({
      fields,
      operationId,
    }: {
      fields: StagedInstrumentField[];
      operationId: string;
    }) => applyInstrumentState(requireLease(lease), instrumentId, fields, operationId),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt) => {
      applyOperationIdRef.current = undefined;
      setApplyResult(receipt.status);
      if (receipt.state) setState(receipt.state);
      if (receipt.status === "applied") {
        collectOperationIdsRef.current = {};
        setCollectResults({});
        setDrafts({});
      } else if (receipt.status === "unknown") {
        onLeaseLost(
          "The apply result is unknown. The daemon quarantined this session for operator review.",
          lease?.expires_at,
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });
  const collectMutation = useMutation({
    mutationFn: ({
      capability,
      stateSnapshot,
      operationId,
    }: {
      capability: InstrumentCapability;
      stateSnapshot?: InstrumentState;
      operationId: string;
    }) =>
      collectInstrumentCapability(
        requireLease(lease),
        instrumentId,
        capability,
        stateSnapshot,
        operationId,
      ),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt, { capability }) => {
      delete collectOperationIdsRef.current[capability.id];
      setCollectResults((current) => ({ ...current, [capability.id]: receipt }));
      if (receipt.status === "unknown") {
        onLeaseLost(
          "The collection result is unknown. The daemon quarantined this session for operator review.",
          lease?.expires_at,
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });
  const resolveMutation = useMutation({
    mutationFn: () => {
      if (instrument.owner_kind !== "instrument_session" || !instrument.owner_id) {
        throw new Error("This attention state is not owned by an interactive session.");
      }
      return resolveInstrumentAttention(instrument.owner_id);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });

  const stage = (
    capability: InstrumentCapability,
    field: InstrumentCapabilityField,
    draft?: DraftValue,
  ) => {
    const key = fieldKey(capability.id, field.id);
    applyOperationIdRef.current = undefined;
    setDrafts((current) => {
      const next = { ...current };
      if (draft === undefined) delete next[key];
      else next[key] = draft;
      return next;
    });
    setApplyResult(undefined);
    applyMutation.reset();
  };
  const applyStaged = () => {
    applyOperationIdRef.current ??= createInstrumentOperationId("apply");
    applyMutation.mutate({
      fields: stagedFields,
      operationId: applyOperationIdRef.current,
    });
  };
  const resetStaged = () => {
    applyOperationIdRef.current = undefined;
    setDrafts({});
    applyMutation.reset();
  };
  const collectCapability = (capability: InstrumentCapability) => {
    const operationId =
      collectOperationIdsRef.current[capability.id] ?? createInstrumentOperationId("collect");
    collectOperationIdsRef.current[capability.id] = operationId;
    collectMutation.mutate({
      capability,
      stateSnapshot: state,
      operationId,
    });
  };
  const interactionError =
    sessionError ??
    mutationError(readMutation.error) ??
    mutationError(applyMutation.error) ??
    mutationError(collectMutation.error) ??
    mutationError(resolveMutation.error);

  return (
    <section className="instrument-inspector" aria-live="polite">
      <header className="instrument-inspector-header">
        <div>
          <div className="instrument-title-row">
            <h2>{description?.label ?? instrumentId}</h2>
            <AvailabilityBadge availability={instrument.availability} connected={connected} />
          </div>
          <code>{instrumentId}</code>
          {description?.description && <p>{description.description}</p>}
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={onEditConnection}
          disabled={
            !connectionEditable ||
            connected ||
            instrument.availability === "active" ||
            instrument.availability === "quarantined"
          }
          title={
            !connectionEditable
              ? "Virtual connections have no editable endpoint"
              : connected
                ? "Disconnect before changing the immutable config"
                : instrument.availability === "active" || instrument.availability === "quarantined"
                  ? "Resolve the current owner before changing the immutable config"
                  : undefined
          }
        >
          <Pencil size={14} />
          Edit connection
        </button>
      </header>

      <InstrumentSessionPanel
        instrument={instrument}
        lease={lease}
        connected={connected}
        actor={actor}
        connectPending={connectPending}
        closePending={closePending}
        refreshPending={readMutation.isPending}
        resolvePending={resolveMutation.isPending}
        onActorChange={onActorChange}
        onConnect={onConnect}
        onClose={onClose}
        onRefresh={() => readMutation.mutate()}
        onResolve={() => resolveMutation.mutate()}
      />

      {interactionError && (
        <div className="instrument-inline-error" role="alert">
          <AlertTriangle size={15} />
          {interactionError}
        </div>
      )}

      {(instrument.problems ?? []).length > 0 && (
        <div className="instrument-problems" role="status">
          <strong>Driver is unavailable</strong>
          {instrument.problems.map((problem, index) => (
            <p key={`${problem.code}-${index}`}>{problem.message}</p>
          ))}
        </div>
      )}

      {description ? (
        <>
          <div className="capability-heading">
            <div>
              <span className="eyebrow">Driver contract</span>
              <h3>Capabilities</h3>
            </div>
            <div>
              <code>{description.implementation_id}</code>
              <small>{versionLabel(description.implementation_version)}</small>
            </div>
          </div>

          {(description.capabilities ?? []).length > 0 ? (
            <div className="capability-list">
              {(description.capabilities ?? []).map((capability) => (
                <CapabilityCard
                  key={capability.id}
                  capability={capability}
                  connected={interactionEnabled}
                  state={state}
                  drafts={drafts}
                  collectResult={collectResults[capability.id]}
                  collecting={
                    collectMutation.isPending &&
                    collectMutation.variables?.capability.id === capability.id
                  }
                  onStage={(field, draft) => stage(capability, field, draft)}
                  onCollect={() => collectCapability(capability)}
                />
              ))}
            </div>
          ) : (
            <InspectorEmpty
              icon={<CircleOff />}
              title="No interactive capabilities"
              detail="This driver does not declare GUI-safe fields or products."
            />
          )}

          {connected && Object.keys(drafts).length > 0 && (
            <div className="staged-apply-bar">
              <div>
                <strong>
                  {Object.keys(drafts).length} staged{" "}
                  {Object.keys(drafts).length === 1 ? "field" : "fields"}
                </strong>
                <small>Values remain local until you apply the complete staged change once.</small>
              </div>
              <button
                type="button"
                className="secondary-button"
                onClick={resetStaged}
                disabled={applyMutation.isPending}
              >
                <RotateCcw size={14} />
                Reset
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={applyStaged}
                disabled={
                  closePending ||
                  invalidDraft ||
                  stagedFields.length === 0 ||
                  applyMutation.isPending
                }
              >
                {applyMutation.isPending ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <Check size={14} />
                )}
                Apply staged
              </button>
            </div>
          )}
          {applyResult && (
            <p className={`instrument-receipt ${applyResult}`}>
              Apply receipt: {titleCase(applyResult)}
            </p>
          )}
        </>
      ) : (
        <InspectorEmpty
          icon={<CircleOff />}
          title="Driver description unavailable"
          detail="Review the listed provider problem or edit this instrument’s connection configuration."
        />
      )}
    </section>
  );
}

function InstrumentSessionPanel({
  instrument,
  lease,
  connected,
  actor,
  connectPending,
  closePending,
  refreshPending,
  resolvePending,
  onActorChange,
  onConnect,
  onClose,
  onRefresh,
  onResolve,
}: {
  instrument: InstrumentView;
  lease?: InstrumentSessionLease;
  connected: boolean;
  actor: string;
  connectPending: boolean;
  closePending: boolean;
  refreshPending: boolean;
  resolvePending: boolean;
  onActorChange: (actor: string) => void;
  onConnect: () => void;
  onClose: () => void;
  onRefresh: () => void;
  onResolve: () => void;
}) {
  if (connected && lease) {
    return (
      <div className="instrument-session-panel connected">
        <div className="session-summary">
          <span aria-hidden="true">
            <Cable size={16} />
          </span>
          <div>
            <strong>Interactive session connected</strong>
            <small>
              {lease.actor} · expires {formatRelative(lease.expires_at)} ·{" "}
              <code>{lease.session_id}</code>
            </small>
          </div>
        </div>
        <div className="session-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={onRefresh}
            disabled={refreshPending || closePending}
          >
            <RefreshCw className={refreshPending ? "spin" : undefined} size={14} />
            Refresh state
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={onClose}
            disabled={closePending}
          >
            {closePending ? <LoaderCircle className="spin" size={14} /> : <Unplug size={14} />}
            Disconnect
          </button>
        </div>
      </div>
    );
  }

  if (instrument.availability === "quarantined") {
    const canResolve =
      instrument.owner_kind === "instrument_session" && Boolean(instrument.owner_id);
    return (
      <div className="instrument-attention-panel">
        <ShieldAlert size={19} aria-hidden="true" />
        <div>
          <strong>Operator resolution required</strong>
          <p>The previous operation left hardware state uncertain. Automatic reuse is blocked.</p>
          <OwnerDescription instrument={instrument} />
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={onResolve}
          disabled={!canResolve || resolvePending}
          title={
            canResolve
              ? "Acknowledge the quarantined interactive session and release it"
              : "Resolve this owner from its run workflow"
          }
        >
          {resolvePending ? <LoaderCircle className="spin" size={14} /> : <ShieldAlert size={14} />}
          Resolve quarantine
        </button>
      </div>
    );
  }

  if (instrument.availability === "active") {
    return (
      <div className="instrument-busy-panel">
        <Database size={18} aria-hidden="true" />
        <div>
          <strong>Read-only while owned</strong>
          <p>Another run or interactive session holds the exclusive instrument lease.</p>
          <OwnerDescription instrument={instrument} />
        </div>
      </div>
    );
  }

  if (instrument.availability === "unavailable") {
    return (
      <div className="instrument-busy-panel unavailable">
        <CircleOff size={18} aria-hidden="true" />
        <div>
          <strong>Connection unavailable</strong>
          <p>Fix the provider or connection configuration before opening a session.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="instrument-session-panel">
      <div className="connect-prompt">
        <strong>Connect only when you are ready to interact</strong>
        <small>
          Opening a session takes an exclusive lease. Selecting this instrument never connects it.
        </small>
      </div>
      <label className="instrument-actor-field">
        <span>Actor</span>
        <input
          value={actor}
          onChange={(event) => onActorChange(event.target.value)}
          aria-label="Instrument session actor"
        />
      </label>
      <button
        type="button"
        className="primary-button"
        onClick={onConnect}
        disabled={connectPending || !actor.trim()}
      >
        {connectPending ? <LoaderCircle className="spin" size={14} /> : <Cable size={14} />}
        Connect
      </button>
    </div>
  );
}

function OwnerDescription({ instrument }: { instrument: InstrumentView }) {
  const ownerKind = instrument.owner_kind === "run" ? "Run" : "Interactive session";
  return (
    <dl className="instrument-owner">
      <div>
        <dt>Owner</dt>
        <dd>
          {ownerKind} <code>{instrument.owner_id}</code>
        </dd>
      </div>
      {instrument.owner_actor && (
        <div>
          <dt>Actor</dt>
          <dd>{instrument.owner_actor}</dd>
        </div>
      )}
      {instrument.expires_at && (
        <div>
          <dt>Expiry</dt>
          <dd title={formatDateTime(instrument.expires_at)}>
            {formatRelative(instrument.expires_at)}
          </dd>
        </div>
      )}
    </dl>
  );
}

function CapabilityCard({
  capability,
  connected,
  state,
  drafts,
  collectResult,
  collecting,
  onStage,
  onCollect,
}: {
  capability: InstrumentCapability;
  connected: boolean;
  state?: InstrumentState;
  drafts: Record<string, DraftValue>;
  collectResult?: InstrumentCollectReceipt;
  collecting: boolean;
  onStage: (field: InstrumentCapabilityField, draft?: DraftValue) => void;
  onCollect: () => void;
}) {
  const products = capability.products ?? [];
  const collectionReadiness = instrumentCollectionReadiness(capability, state);
  const collectionBlocked = !collectionReadiness.ready;
  const collectionReasonId = `collect-reason-${capability.id}`;
  return (
    <article className="capability-card" aria-labelledby={`capability-${capability.id}`}>
      <header>
        <div>
          <h4 id={`capability-${capability.id}`}>{capability.label ?? titleCase(capability.id)}</h4>
          <code>{capability.id}</code>
          {capability.description && <p>{capability.description}</p>}
        </div>
        {products.length > 0 && (
          <div className="capability-collect-action">
            <button
              type="button"
              className="secondary-button"
              onClick={onCollect}
              disabled={!connected || collecting || collectionBlocked}
              aria-describedby={connected && collectionBlocked ? collectionReasonId : undefined}
              title={
                !connected
                  ? "Connect before collecting"
                  : collectionBlocked
                    ? collectionReadiness.reason
                    : undefined
              }
            >
              {collecting ? <LoaderCircle className="spin" size={14} /> : <Database size={14} />}
              Collect
            </button>
            {connected && collectionBlocked && (
              <small id={collectionReasonId} className="collection-blocked-reason">
                <AlertTriangle size={12} aria-hidden="true" />
                {collectionReadiness.reason}
              </small>
            )}
          </div>
        )}
      </header>

      {(capability.fields ?? []).length > 0 && (
        <div className="capability-fields">
          {(capability.fields ?? []).map((field) => {
            const key = fieldKey(capability.id, field.id);
            return (
              <CapabilityFieldEditor
                key={field.id}
                field={field}
                currentValue={stateValue(state, capability.id, field.id)}
                draft={drafts[key]}
                editable={connected && field.access !== "read_only"}
                onChange={(draft) => onStage(field, draft)}
              />
            );
          })}
        </div>
      )}

      {products.length > 0 && (
        <div className="capability-products">
          <span>Products</span>
          {products.map((product) => (
            <span key={product.key} className="product-chip">
              {product.label ?? product.key}
              <small>
                {product.dtype}
                {product.unit ? ` · ${product.unit}` : ""}
              </small>
            </span>
          ))}
        </div>
      )}

      {collectResult && <CollectPreview receipt={collectResult} />}
    </article>
  );
}

function CapabilityFieldEditor({
  field,
  currentValue,
  draft,
  editable,
  onChange,
}: {
  field: InstrumentCapabilityField;
  currentValue?: InstrumentStateValue;
  draft?: DraftValue;
  editable: boolean;
  onChange: (draft?: DraftValue) => void;
}) {
  const type = field.value_type;
  const value = draft?.raw ?? inputValue(currentValue, type.type);
  const dirty = draft !== undefined;
  return (
    <label className={`capability-field ${dirty ? "staged" : ""}`}>
      <span className="field-label">
        <span>
          <strong>{field.label ?? titleCase(field.id)}</strong>
          <code>{field.id}</code>
        </span>
        <small>{accessLabel(field.access)}</small>
      </span>
      {type.type === "bool" ? (
        <span className="boolean-editor">
          <input
            type="checkbox"
            checked={typeof value === "boolean" ? value : false}
            disabled={!editable}
            onChange={(event) =>
              onChange({ raw: event.target.checked, value: event.target.checked })
            }
          />
          {typeof value === "boolean" ? (value ? "On" : "Off") : "Unknown"}
        </span>
      ) : type.type === "string" && type.choices ? (
        <select
          value={typeof value === "string" ? value : ""}
          disabled={!editable}
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
      ) : type.type === "int" || type.type === "float" || type.type === "quantity" ? (
        <span className="number-unit-editor">
          <input
            type="number"
            step={type.type === "int" ? 1 : "any"}
            min={type.minimum ?? undefined}
            max={type.maximum ?? undefined}
            value={typeof value === "string" || typeof value === "number" ? value : ""}
            placeholder={editable ? "Enter value" : "—"}
            disabled={!editable}
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
      ) : type.type === "string" ? (
        <input
          type="text"
          value={typeof value === "string" ? value : ""}
          placeholder={editable ? "Enter value" : "—"}
          disabled={!editable}
          onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
        />
      ) : (
        <input type="text" value="Payload editing unavailable in GUI" disabled />
      )}
      {field.description && <small className="field-description">{field.description}</small>}
      {dirty && (
        <button type="button" className="field-reset" onClick={() => onChange()}>
          Reset staged value
        </button>
      )}
    </label>
  );
}

function CollectPreview({ receipt }: { receipt: InstrumentCollectReceipt }) {
  const trace = traceValues(receipt);
  return (
    <div className={`collect-preview ${receipt.status}`}>
      <div>
        <strong>Collect receipt: {titleCase(receipt.status)}</strong>
        {receipt.readback && (
          <small>{Object.keys(receipt.readback.values ?? {}).length} products returned</small>
        )}
      </div>
      {trace && <TracePreview values={trace} />}
      <details>
        <summary>JSON preview</summary>
        <pre>{JSON.stringify(receipt.readback ?? receipt, null, 2)}</pre>
      </details>
    </div>
  );
}

function TracePreview({ values }: { values: number[] }) {
  if (values.length === 0) return null;
  const width = 420;
  const height = 100;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = maximum - minimum || 1;
  const points = values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width;
      const y = height - ((value - minimum) / range) * (height - 8) - 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className="instrument-trace"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${values.length}-point trace preview`}
      preserveAspectRatio="none"
    >
      <polyline points={points} />
    </svg>
  );
}

function InspectorEmpty({
  icon,
  title,
  detail,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="instrument-inspector-empty">
      <span aria-hidden="true">{icon}</span>
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

export function AvailabilityBadge({
  availability,
  connected = false,
}: {
  availability: InstrumentView["availability"];
  connected?: boolean;
}) {
  const label = connected ? "Connected" : titleCase(availability);
  return (
    <span className={`instrument-availability ${connected ? "connected" : availability}`}>
      <span aria-hidden="true" />
      {label}
    </span>
  );
}

function stateValue(
  state: InstrumentState | undefined,
  capabilityId: string,
  fieldPath: string,
): InstrumentStateValue | undefined {
  return (state?.fields ?? []).find(
    (field) => field.capability_id === capabilityId && field.field_path === fieldPath,
  )?.value;
}

function inputValue(
  value: InstrumentStateValue | undefined,
  type: InstrumentCapabilityField["value_type"]["type"],
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

function stagedInstrumentFields(drafts: Record<string, DraftValue>): StagedInstrumentField[] {
  return Object.entries(drafts).flatMap(([key, draft]) => {
    if (draft.value === undefined) return [];
    const separator = key.indexOf("\u0000");
    return [
      {
        capabilityId: key.slice(0, separator),
        fieldPath: key.slice(separator + 1),
        value: draft.value,
      },
    ];
  });
}

function fieldKey(capabilityId: string, fieldPath: string): string {
  return `${capabilityId}\u0000${fieldPath}`;
}

function accessLabel(access: InstrumentCapabilityField["access"]): string {
  if (access === "read_only") return "Read only";
  if (access === "write_only") return "Write only";
  return "Read / write";
}

function versionLabel(version: string): string {
  return /^v/i.test(version) ? version : `v${version}`;
}

function requireLease(lease: InstrumentSessionLease | undefined): InstrumentSessionLease {
  if (!lease) throw new Error("Connect the instrument before interacting with it.");
  return lease;
}

function mutationError(error: unknown): string | undefined {
  return error === null || error === undefined ? undefined : errorMessage(error);
}

function traceValues(receipt: InstrumentCollectReceipt): number[] | undefined {
  for (const value of Object.values(receipt.readback?.values ?? {})) {
    if (
      typeof value === "object" &&
      value !== null &&
      "values" in value &&
      Array.isArray(value.values)
    ) {
      const samples = value.values
        .map((sample) => {
          if (typeof sample === "number" && Number.isFinite(sample)) return sample;
          if (
            typeof sample === "object" &&
            sample !== null &&
            "real" in sample &&
            "imag" in sample &&
            typeof sample.real === "number" &&
            typeof sample.imag === "number"
          ) {
            return Math.hypot(sample.real, sample.imag);
          }
          return undefined;
        })
        .filter((sample): sample is number => sample !== undefined);
      if (samples.length > 0) return samples;
    }
  }
  return undefined;
}
