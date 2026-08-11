"""Volatile state and replay records for instrument runtime coordination."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock

from scopecat.daemon.wire import (
    InstrumentConfiguredDefaultsApplyCommand,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
)
from scopecat.records.config import InstrumentBindingSpec, InstrumentSpec
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.commands import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentConfiguredDefaultsApplyReceipt,
    InstrumentStateCommand,
    InteractiveCollectIntent,
    InvokeCommand,
    InvokeReceipt,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareBatchReceipt,
    RunHardwareFinalizationReceipt,
)
from scopecat.sdk.payloads import PayloadCodecCatalog

from .actors import OwnedInstrument

INTERACTIVE_REPLAY_LIMIT = 256


@dataclass(slots=True)
class InstrumentOperationLedger:
    _operations: OrderedDict[str, InstrumentOperationReplay] = field(
        default_factory=OrderedDict
    )

    def replay(self, command_id: str) -> InstrumentOperationReplay | None:
        return self._operations.get(command_id)

    def remember(
        self,
        command_id: str,
        replay: InstrumentOperationReplay,
    ) -> None:
        self._operations[command_id] = replay
        self._operations.move_to_end(command_id)
        if len(self._operations) > INTERACTIVE_REPLAY_LIMIT:
            self._operations.popitem(last=False)


@dataclass(frozen=True, slots=True)
class ApplyReplay:
    command: InstrumentStateCommand
    receipt: ApplyReceipt


@dataclass(frozen=True, slots=True)
class InvokeReplay:
    command: InvokeCommand
    receipt: InvokeReceipt


@dataclass(frozen=True, slots=True)
class CollectReceiptReplay:
    intent: InteractiveCollectIntent
    command: CollectCommand
    receipt: CollectReceipt


@dataclass(frozen=True, slots=True)
class CollectRejectionReplay:
    intent: InteractiveCollectIntent
    receipt: CollectReceipt


@dataclass(frozen=True, slots=True)
class CollectFailureReplay:
    intent: InteractiveCollectIntent
    command: CollectCommand
    message: str


@dataclass(frozen=True, slots=True)
class ConfiguredDefaultsReplay:
    command: InstrumentConfiguredDefaultsApplyCommand
    receipt: InstrumentConfiguredDefaultsApplyReceipt


type InstrumentOperationReplay = (
    ApplyReplay
    | InvokeReplay
    | CollectReceiptReplay
    | CollectRejectionReplay
    | CollectFailureReplay
    | ConfiguredDefaultsReplay
)


@dataclass(slots=True)
class OwnershipRuntime:
    instruments: dict[str, OwnedInstrument]
    bindings: dict[str, InstrumentBindingSpec]
    specs: dict[str, InstrumentSpec]
    payload_catalog: PayloadCodecCatalog
    ledgers: dict[str, InstrumentOperationLedger]
    opening_state: tuple[InstrumentStateSnapshot, ...] = ()
    lock: RLock = field(default_factory=RLock)


@dataclass(slots=True)
class SessionContext:
    runtime: OwnershipRuntime
    lease_lock: RLock = field(default_factory=RLock)


@dataclass(frozen=True, slots=True)
class RunFinalizing:
    pass


@dataclass(frozen=True, slots=True)
class RunFinalized:
    command: RunHardwareFinishCommand
    receipt: RunHardwareFinalizationReceipt


type RunFinalization = RunFinalizing | RunFinalized


@dataclass(frozen=True, slots=True)
class RunProvision:
    command: RunInstrumentProvisionCommand
    receipt: RunInstrumentProvisionReceipt
    batches: dict[
        str,
        tuple[RunHardwareBatchCommand, RunHardwareBatchReceipt],
    ] = field(default_factory=dict)


@dataclass(slots=True)
class RunContext:
    """Serialize one run and retain volatile receipts only until ``release_run``."""

    lock: RLock = field(default_factory=RLock)
    provision: RunProvision | None = None
    runtime: OwnershipRuntime | None = None
    finalization: RunFinalization | None = None
