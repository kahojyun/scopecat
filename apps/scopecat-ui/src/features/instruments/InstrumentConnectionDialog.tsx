import { useMemo, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { Cable, LoaderCircle, Save, X } from "lucide-react";
import type { InstrumentConnection } from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { publishInstrumentConnection, type ActiveConfig } from "./instrument-api";

type TcpipInstrumentConnection = Extract<InstrumentConnection, { kind: "tcpip_socket" }>;

export function InstrumentConnectionDialog({
  active,
  instrumentId,
  onCancel,
  onPublished,
}: {
  active: ActiveConfig;
  instrumentId: string;
  onCancel: () => void;
  onPublished: () => void | Promise<void>;
}) {
  const spec = active.config.system.instrument_registry.instruments.find(
    (instrument) => instrument.id === instrumentId,
  );
  if (!spec) {
    return <MissingInstrumentDialog instrumentId={instrumentId} onCancel={onCancel} />;
  }
  if (spec.connection.kind !== "tcpip_socket") return null;
  return (
    <ConnectionEditor
      active={active}
      instrumentId={instrumentId}
      driverId={spec.driver_id}
      initialConnection={spec.connection}
      onCancel={onCancel}
      onPublished={onPublished}
    />
  );
}

function ConnectionEditor({
  active,
  instrumentId,
  driverId,
  initialConnection,
  onCancel,
  onPublished,
}: {
  active: ActiveConfig;
  instrumentId: string;
  driverId: string;
  initialConnection: TcpipInstrumentConnection;
  onCancel: () => void;
  onPublished: () => void | Promise<void>;
}) {
  const [connection, setConnection] = useState<TcpipInstrumentConnection>(initialConnection);
  const [actor, setActor] = useState("local-operator");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const changed = useMemo(
    () => JSON.stringify(connection) !== JSON.stringify(initialConnection),
    [connection, initialConnection],
  );
  const valid = useMemo(
    () => changed && connectionIsValid(connection) && actor.trim().length > 0,
    [actor, changed, connection],
  );

  const publish = async () => {
    if (!valid) return;
    setPending(true);
    setError(undefined);
    try {
      await publishInstrumentConnection({
        active,
        instrumentId,
        connection,
        actor: actor.trim(),
        note: note.trim(),
      });
      await onPublished();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(open) => !open && !pending && onCancel()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="dialog-popup config-modal instrument-connection-modal">
            <header>
              <span aria-hidden="true">
                <Cable size={19} />
              </span>
              <div>
                <Dialog.Title className="dialog-title">Edit instrument connection</Dialog.Title>
                <Dialog.Description className="dialog-description">
                  {instrumentId} · publishes a new immutable default
                </Dialog.Description>
              </div>
              <Dialog.Close
                className="icon-button"
                aria-label="Close connection editor"
                disabled={pending}
              >
                <X size={16} />
              </Dialog.Close>
            </header>
            <div className="config-modal-body instrument-connection-form">
              <div className="instrument-connection-identity">
                <div>
                  <span>Driver</span>
                  <code>{driverId}</code>
                </div>
                <div>
                  <span>Connection type</span>
                  <strong>TCP/IP socket</strong>
                </div>
              </div>
              <p className="connection-scope-note">
                Driver, connection type, and driver options come from the active configuration. This
                editor only publishes endpoint and timeout changes.
              </p>
              <ConnectionFields connection={connection} onChange={setConnection} />
              <div className="instrument-config-audit">
                <label>
                  <span>Actor</span>
                  <input
                    value={actor}
                    onChange={(event) => setActor(event.target.value)}
                    aria-label="Configuration actor"
                  />
                </label>
                <label>
                  <span>Note</span>
                  <input
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="Why is this connection changing?"
                  />
                </label>
              </div>
              {error && (
                <div className="instrument-inline-error" role="alert">
                  {error}
                </div>
              )}
            </div>
            <footer>
              <Dialog.Close className="secondary-button" disabled={pending}>
                Cancel
              </Dialog.Close>
              <button
                type="button"
                className="primary-button"
                disabled={!valid || pending}
                onClick={() => void publish()}
              >
                {pending ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                Publish default
              </button>
            </footer>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ConnectionFields({
  connection,
  onChange,
}: {
  connection: TcpipInstrumentConnection;
  onChange: (connection: TcpipInstrumentConnection) => void;
}) {
  return (
    <div className="instrument-connection-fields two-column">
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
        onChange={(port) => onChange({ ...connection, port })}
      />
      <TimeoutField
        value={connection.timeout_seconds}
        onChange={(timeout_seconds) => onChange({ ...connection, timeout_seconds })}
      />
    </div>
  );
}

function TimeoutField({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return (
    <NumberField label="Timeout (seconds)" value={value} minimum={0.001} onChange={onChange} />
  );
}

function NumberField({
  label,
  value,
  minimum,
  maximum,
  onChange,
}: {
  label: string;
  value: number;
  minimum: number;
  maximum?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={minimum}
        max={maximum}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function connectionIsValid(connection: TcpipInstrumentConnection): boolean {
  return (
    connection.host.trim().length > 0 &&
    Number.isInteger(connection.port) &&
    connection.port >= 1 &&
    connection.port <= 65_535 &&
    connection.timeout_seconds > 0
  );
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
                  {instrumentId} is no longer present in the active configuration. Refresh the
                  instrument index before editing.
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
