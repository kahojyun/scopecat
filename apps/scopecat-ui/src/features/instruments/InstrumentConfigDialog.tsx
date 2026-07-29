import { useMemo, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { Cable, Check, LoaderCircle, PlugZap, Save, X } from "lucide-react";
import type {
  DriverCatalog,
  DriverConnectionSpec,
  DriverSpec,
  InstrumentConnection,
  InstrumentDriverProbeReceipt,
  InstrumentSpec,
} from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { probeInstrumentDriver, publishInstrumentSpec, type ActiveConfig } from "./instrument-api";

type ConnectionKind = InstrumentConnection["kind"];
type TcpConnection = Extract<InstrumentConnection, { kind: "tcpip_socket" }>;
type OptionValue = number | boolean;
type ConnectionOptions = NonNullable<InstrumentConnection["options"]>;

interface OptionField {
  id: string;
  label: string;
  type: "boolean" | "integer";
  defaultValue?: OptionValue;
  minimum?: number;
  maximum?: number;
}

export function InstrumentConfigDialog({
  active,
  catalog,
  instrumentId,
  onCancel,
  onPublished,
}: {
  active: ActiveConfig;
  catalog: DriverCatalog;
  instrumentId?: string;
  onCancel: () => void;
  onPublished: (instrumentId: string) => void | Promise<void>;
}) {
  const existing = instrumentId
    ? active.config.system.instrument_registry.instruments.find(
        (instrument) => instrument.id === instrumentId,
      )
    : undefined;
  if (instrumentId && !existing) {
    return <MissingInstrumentDialog instrumentId={instrumentId} onCancel={onCancel} />;
  }
  return (
    <InstrumentConfigEditor
      active={active}
      catalog={catalog}
      existing={existing}
      onCancel={onCancel}
      onPublished={onPublished}
    />
  );
}

function InstrumentConfigEditor({
  active,
  catalog,
  existing,
  onCancel,
  onPublished,
}: {
  active: ActiveConfig;
  catalog: DriverCatalog;
  existing?: InstrumentSpec;
  onCancel: () => void;
  onPublished: (instrumentId: string) => void | Promise<void>;
}) {
  const initialDriver = catalog.drivers.find((driver) => driver.driver_id === existing?.driver_id);
  const firstDriver = initialDriver ?? catalog.drivers[0];
  const [instrumentId, setInstrumentId] = useState(existing?.id ?? "");
  const [driverId, setDriverId] = useState(existing?.driver_id ?? firstDriver?.driver_id ?? "");
  const [connection, setConnection] = useState<InstrumentConnection>(() =>
    initialConnection(existing?.connection, firstDriver),
  );
  const [note, setNote] = useState("");
  const [probe, setProbe] = useState<InstrumentDriverProbeReceipt>();
  const [probePending, setProbePending] = useState(false);
  const [publishPending, setPublishPending] = useState(false);
  const [error, setError] = useState<string>();
  const driver = catalog.drivers.find((candidate) => candidate.driver_id === driverId);
  const connectionSpec = driver?.connections.find(
    (candidate) => candidate.kind === connection.kind,
  );
  const optionFields = useMemo(
    () => scalarOptionFields(connectionSpec?.options_schema),
    [connectionSpec?.options_schema],
  );
  const options = connection.options ?? {};
  const spec = useMemo(
    () => proposedSpec(instrumentId.trim(), driverId, connection, existing),
    [connection, driverId, existing, instrumentId],
  );
  const changed = !existing || JSON.stringify(spec) !== JSON.stringify(existing);
  const valid =
    driver !== undefined &&
    driver.connections.some((candidate) => candidate.kind === connection.kind) &&
    spec.id.length > 0 &&
    !(
      !existing &&
      active.config.system.instrument_registry.instruments.some(
        (candidate) => candidate.id === spec.id,
      )
    ) &&
    connectionIsValid(connection) &&
    optionsAreValid(options, optionFields);
  const busy = probePending || publishPending;

  const chooseDriver = (nextDriverId: string) => {
    const nextDriver = catalog.drivers.find((candidate) => candidate.driver_id === nextDriverId);
    setDriverId(nextDriverId);
    setConnection(initialConnection(undefined, nextDriver));
    clearFeedback();
  };
  const chooseConnectionKind = (kind: ConnectionKind) => {
    const nextSpec = driver?.connections.find((candidate) => candidate.kind === kind);
    setConnection(newConnection(kind, nextSpec));
    clearFeedback();
  };
  const updateConnection = (next: InstrumentConnection) => {
    setConnection(next);
    clearFeedback();
  };
  const testConnection = async () => {
    if (!valid) return;
    setProbePending(true);
    setError(undefined);
    setProbe(undefined);
    try {
      setProbe(
        await probeInstrumentDriver({
          binding: {
            id: spec.id,
            driver_id: spec.driver_id,
            connection: spec.connection,
          },
        }),
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setProbePending(false);
    }
  };
  const publish = async () => {
    if (!valid || !changed) return;
    setPublishPending(true);
    setError(undefined);
    try {
      await publishInstrumentSpec({
        active,
        spec,
        originalInstrumentId: existing?.id,
        actor: "local-operator",
        note: note.trim(),
      });
      await onPublished(spec.id);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPublishPending(false);
    }
  };
  const clearFeedback = () => {
    setProbe(undefined);
    setError(undefined);
  };

  return (
    <Dialog.Root open onOpenChange={(open) => !open && !busy && onCancel()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="dialog-popup config-modal instrument-config-modal">
            <header>
              <span aria-hidden="true">
                <Cable size={19} />
              </span>
              <div>
                <Dialog.Title className="dialog-title">
                  {existing ? "Configure instrument" : "Add instrument"}
                </Dialog.Title>
                <Dialog.Description className="dialog-description">
                  {existing
                    ? `${existing.id} · publishes a new immutable default`
                    : "Choose a registered driver and publish it to the active laboratory config"}
                </Dialog.Description>
              </div>
              <Dialog.Close
                className="icon-button"
                aria-label="Close instrument configuration"
                disabled={busy}
              >
                <X size={16} />
              </Dialog.Close>
            </header>

            <div className="config-modal-body instrument-config-form">
              <div className="instrument-config-fields">
                <label>
                  <span>Instrument ID</span>
                  <input
                    value={instrumentId}
                    disabled={existing !== undefined}
                    onChange={(event) => {
                      setInstrumentId(event.target.value);
                      clearFeedback();
                    }}
                    placeholder="readout-vna"
                  />
                </label>
                <label>
                  <span>Driver</span>
                  <select value={driverId} onChange={(event) => chooseDriver(event.target.value)}>
                    {!driver && <option value={driverId}>Unavailable · {driverId}</option>}
                    {catalog.drivers.map((candidate) => (
                      <option key={candidate.driver_id} value={candidate.driver_id}>
                        {driverLabel(candidate)}
                      </option>
                    ))}
                  </select>
                </label>
                {driver && (
                  <label>
                    <span>Connection</span>
                    <select
                      value={connection.kind}
                      onChange={(event) =>
                        chooseConnectionKind(event.target.value as ConnectionKind)
                      }
                    >
                      {driver.connections.map((candidate) => (
                        <option key={candidate.kind} value={candidate.kind}>
                          {connectionKindLabel(candidate.kind)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>

              {connection.kind === "tcpip_socket" && (
                <TcpConnectionFields connection={connection} onChange={updateConnection} />
              )}

              {optionFields.length > 0 && (
                <fieldset className="instrument-driver-options">
                  <legend>Driver options</legend>
                  <div className="instrument-option-fields">
                    {optionFields.map((field) => (
                      <OptionInput
                        key={field.id}
                        field={field}
                        value={scalarOptionValue(options[field.id]) ?? field.defaultValue}
                        onChange={(value) =>
                          updateConnection({
                            ...connection,
                            options: { ...options, [field.id]: value },
                          })
                        }
                      />
                    ))}
                  </div>
                </fieldset>
              )}

              {existing && existing.driver_id !== driverId && (
                <p className="instrument-config-note">
                  Changing the driver clears configured startup state because property contracts may
                  differ.
                </p>
              )}

              <div className="instrument-config-audit">
                <label>
                  <span>Note</span>
                  <input
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="Why is this device changing?"
                  />
                </label>
              </div>

              <div className="instrument-probe-row">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!valid || busy}
                  onClick={() => void testConnection()}
                >
                  {probePending ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <PlugZap size={15} />
                  )}
                  {probePending ? "Testing connection" : "Test connection"}
                </button>
                {probe && <ProbeResult receipt={probe} />}
              </div>

              {error && (
                <div className="instrument-inline-error" role="alert">
                  {error}
                </div>
              )}
            </div>

            <footer>
              <Dialog.Close className="secondary-button" disabled={busy}>
                Cancel
              </Dialog.Close>
              <button
                type="button"
                className="primary-button"
                disabled={!valid || !changed || busy}
                onClick={() => void publish()}
              >
                {publishPending ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                Publish default
              </button>
            </footer>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function TcpConnectionFields({
  connection,
  onChange,
}: {
  connection: TcpConnection;
  onChange: (connection: TcpConnection) => void;
}) {
  return (
    <div className="instrument-connection-fields">
      <label>
        <span>Host</span>
        <input
          value={connection.host}
          onChange={(event) => onChange({ ...connection, host: event.target.value })}
        />
      </label>
      <NumberField
        label="Port"
        value={connection.port}
        minimum={1}
        maximum={65_535}
        integer
        onChange={(port) => onChange({ ...connection, port })}
      />
      <NumberField
        label="Timeout (seconds)"
        value={connection.timeout_seconds}
        minimum={0.001}
        onChange={(timeout_seconds) => onChange({ ...connection, timeout_seconds })}
      />
    </div>
  );
}

function OptionInput({
  field,
  value,
  onChange,
}: {
  field: OptionField;
  value: OptionValue | undefined;
  onChange: (value: OptionValue) => void;
}) {
  if (field.type === "boolean") {
    return (
      <label className="instrument-option-toggle">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{field.label}</span>
      </label>
    );
  }
  return (
    <NumberField
      label={field.label}
      value={typeof value === "number" ? value : Number.NaN}
      minimum={field.minimum}
      maximum={field.maximum}
      integer
      onChange={onChange}
    />
  );
}

function NumberField({
  label,
  value,
  minimum,
  maximum,
  integer = false,
  onChange,
}: {
  label: string;
  value: number;
  minimum?: number;
  maximum?: number;
  integer?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <input
        type="number"
        value={Number.isNaN(value) ? "" : value}
        min={minimum}
        max={maximum}
        step={integer ? 1 : "any"}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function ProbeResult({ receipt }: { receipt: InstrumentDriverProbeReceipt }) {
  if (receipt.status === "connected") {
    return (
      <span className="instrument-probe-result connected" role="status">
        <Check size={14} />
        {receipt.description?.label
          ? `Connected to ${receipt.description.label}`
          : "Connection succeeded"}
      </span>
    );
  }
  return (
    <span className="instrument-probe-result rejected" role="status">
      {receipt.problems.map((problem) => problem.message).join(" ") || "Connection rejected"}
    </span>
  );
}

function proposedSpec(
  instrumentId: string,
  driverId: string,
  connection: InstrumentConnection,
  existing?: InstrumentSpec,
): InstrumentSpec {
  const preservesState = existing?.driver_id === driverId;
  return {
    id: instrumentId,
    exclusivity_key: existing?.exclusivity_key ?? instrumentId,
    driver_id: driverId,
    connection,
    default_state: preservesState ? existing.default_state : [],
    run_start: preservesState ? existing.run_start : "preserve",
  };
}

function initialConnection(
  existing: InstrumentConnection | undefined,
  driver: DriverSpec | undefined,
): InstrumentConnection {
  const supported = driver?.connections.find((candidate) => candidate.kind === existing?.kind);
  if (existing && supported) {
    const options = {
      ...defaultOptions(supported.options_schema),
      ...existing.options,
    };
    return {
      ...existing,
      ...(existing.options || Object.keys(options).length > 0 ? { options } : {}),
    };
  }
  const connectionSpec = driver?.connections[0];
  return newConnection(connectionSpec?.kind ?? "virtual", connectionSpec);
}

function newConnection(
  kind: ConnectionKind,
  connectionSpec?: DriverConnectionSpec,
): InstrumentConnection {
  const options = defaultOptions(connectionSpec?.options_schema);
  const configuredOptions = Object.keys(options).length > 0 ? { options } : {};
  return kind === "virtual"
    ? { kind, ...configuredOptions }
    : { kind, host: "", port: 5025, timeout_seconds: 5, ...configuredOptions };
}

function connectionIsValid(connection: InstrumentConnection): boolean {
  return (
    connection.kind === "virtual" ||
    (connection.host.trim().length > 0 &&
      Number.isInteger(connection.port) &&
      connection.port >= 1 &&
      connection.port <= 65_535 &&
      Number.isFinite(connection.timeout_seconds) &&
      connection.timeout_seconds > 0)
  );
}

function optionsAreValid(options: ConnectionOptions, fields: OptionField[]): boolean {
  return fields.every((field) => {
    const value = scalarOptionValue(options[field.id]) ?? field.defaultValue;
    if (field.type === "boolean") return typeof value === "boolean";
    return (
      typeof value === "number" &&
      Number.isFinite(value) &&
      Number.isInteger(value) &&
      (field.minimum === undefined || value >= field.minimum) &&
      (field.maximum === undefined || value <= field.maximum)
    );
  });
}

// Driver options stay opaque; the editor projects only the boolean and integer SDK fields in use.
function scalarOptionFields(schema: unknown): OptionField[] {
  if (!isRecord(schema) || !isRecord(schema.properties)) return [];
  return Object.entries(schema.properties).flatMap(([id, value]) => {
    if (!isRecord(value)) return [];
    const type = value.type;
    if (type !== "boolean" && type !== "integer") return [];
    return [
      {
        id,
        label: typeof value.title === "string" ? value.title : titleCase(id),
        type: type as OptionField["type"],
        defaultValue: scalarOptionValue(value.default),
        minimum: typeof value.minimum === "number" ? value.minimum : undefined,
        maximum: typeof value.maximum === "number" ? value.maximum : undefined,
      },
    ];
  });
}

function defaultOptions(schema: unknown): ConnectionOptions {
  return Object.fromEntries(
    scalarOptionFields(schema).flatMap((field) =>
      field.defaultValue === undefined ? [] : [[field.id, field.defaultValue]],
    ),
  ) as ConnectionOptions;
}

function scalarOptionValue(value: unknown): OptionValue | undefined {
  return typeof value === "number" || typeof value === "boolean" ? value : undefined;
}

function driverLabel(driver: DriverSpec): string {
  return driver.manufacturer && driver.model
    ? `${driver.manufacturer} ${driver.model}`
    : driver.label;
}

function connectionKindLabel(kind: ConnectionKind): string {
  return kind === "virtual" ? "Virtual simulator" : "TCP/IP socket";
}

function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function MissingInstrumentDialog({
  instrumentId,
  onCancel,
}: {
  instrumentId: string;
  onCancel: () => void;
}) {
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onCancel()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="dialog-popup confirmation-dialog">
            <div className="dialog-heading">
              <span aria-hidden="true">
                <Cable size={18} />
              </span>
              <div>
                <Dialog.Title className="dialog-title">Instrument changed</Dialog.Title>
                <Dialog.Description className="dialog-description">
                  {instrumentId} is no longer present in the active configuration. Refresh before
                  editing.
                </Dialog.Description>
              </div>
            </div>
            <div className="dialog-actions">
              <Dialog.Close className="secondary-button">Close</Dialog.Close>
            </div>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
