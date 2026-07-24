import { useState } from "react";
import { AlertDialog } from "@base-ui/react/alert-dialog";
import { AlertTriangle } from "lucide-react";

export interface ConfirmationRequest {
  title: string;
  description: string;
  confirmLabel: string;
  intent?: "default" | "danger";
  onConfirm: () => void;
}

export function useConfirmationDialog() {
  const [request, setRequest] = useState<ConfirmationRequest>();

  return {
    requestConfirmation: setRequest,
    confirmationDialog: request ? (
      <ConfirmationDialog request={request} onClose={() => setRequest(undefined)} />
    ) : null,
  };
}

function ConfirmationDialog({
  request,
  onClose,
}: {
  request: ConfirmationRequest;
  onClose: () => void;
}) {
  const confirm = () => {
    onClose();
    request.onConfirm();
  };

  return (
    <AlertDialog.Root open onOpenChange={(open) => !open && onClose()}>
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className="dialog-backdrop" />
        <AlertDialog.Viewport className="dialog-viewport">
          <AlertDialog.Popup className="dialog-popup confirmation-dialog">
            <header className="dialog-heading">
              <span
                className={request.intent === "danger" ? "danger" : undefined}
                aria-hidden="true"
              >
                <AlertTriangle size={18} />
              </span>
              <div>
                <AlertDialog.Title className="dialog-title">{request.title}</AlertDialog.Title>
                <AlertDialog.Description className="dialog-description">
                  {request.description}
                </AlertDialog.Description>
              </div>
            </header>
            <footer className="dialog-actions">
              <AlertDialog.Close className="secondary-button">Cancel</AlertDialog.Close>
              <AlertDialog.Close
                className={
                  request.intent === "danger" ? "primary-button danger-button" : "primary-button"
                }
                onClick={confirm}
              >
                {request.confirmLabel}
              </AlertDialog.Close>
            </footer>
          </AlertDialog.Popup>
        </AlertDialog.Viewport>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
