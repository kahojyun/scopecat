"""Notebook-facing direct instrument interaction."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Self
from uuid import uuid4

from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import InstrumentListView, InstrumentView
from scopecat.daemon.wire import (
    InstrumentSessionEndReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
)
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectAxisRequest,
    CollectCommand,
    CollectProductRequest,
    CollectReceipt,
    InstrumentDescription,
    InstrumentStateCommand,
    InstrumentStateCommandField,
)


class LabInstrumentOperations:
    """Discover configured instruments and create daemon-owned live sessions."""

    def __init__(
        self,
        client: DaemonClient,
        *,
        operator: str,
    ) -> None:
        self._client = client
        self._operator = operator

    def list(self) -> InstrumentListView:
        return self._client.list_instruments()

    def get(self, instrument_id: str) -> InstrumentView:
        return self._client.get_instrument(instrument_id)

    def abort_session(self, session_id: str) -> InstrumentSessionEndReceipt:
        """Abort and release a daemon-owned session by id."""

        return self._client.abort_instrument_session(session_id)

    def open(
        self,
        instrument_id: str,
        *additional_instrument_ids: str,
        actor: str | None = None,
        operation_id: str | None = None,
    ) -> InstrumentSessionHandle:
        return InstrumentSessionHandle(
            client=self._client,
            instrument_ids=(instrument_id, *additional_instrument_ids),
            actor=actor or self._operator,
            open_operation_id=operation_id,
        )


class InstrumentSessionHandle:
    """Context-managed direct access to one or more live drivers."""

    def __init__(
        self,
        *,
        client: DaemonClient,
        instrument_ids: tuple[str, ...],
        actor: str,
        open_operation_id: str | None = None,
    ) -> None:
        if not instrument_ids or any(not item for item in instrument_ids):
            raise ValueError("direct interaction requires non-empty instrument ids")
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("direct interaction instrument ids must be unique")
        if not actor:
            raise ValueError("direct interaction actor must be non-empty")
        self._client = client
        self._instrument_ids = instrument_ids
        self._actor = actor
        self._open_operation_id = _select_operation_id(
            open_operation_id,
            kind="open",
            subject=instrument_ids[0],
        )
        self._session: InstrumentSessionOpenReceipt | None = None
        self._ended = False

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is None:
            self.close()
        else:
            self.abort()

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        return self._instrument_ids

    @property
    def session_id(self) -> str:
        return self._require_session().session_id

    def describe(
        self,
        instrument_id: str | None = None,
    ) -> InstrumentDescription:
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        return next(
            description
            for description in session.descriptions
            if description.instrument_id == selected
        )

    def read_state(
        self,
        instrument_id: str | None = None,
    ) -> InstrumentStateSnapshot:
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        return self._client.read_instrument_state(
            session.session_id,
            selected,
        )

    def apply(
        self,
        capability_id: str,
        values: Mapping[str, StateLiteral | StateValue] | None = None,
        /,
        *,
        instrument_id: str | None = None,
        operation_id: str | None = None,
        **fields: StateLiteral | StateValue,
    ) -> ApplyReceipt:
        if values is not None and fields:
            raise ValueError("pass state fields as a mapping or keyword values")
        selected_values = dict(values or fields)
        if not selected_values:
            raise ValueError("interactive apply requires at least one field")
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        selected_operation_id = _select_operation_id(
            operation_id,
            kind="apply",
            subject=selected,
        )
        command = InstrumentStateCommand(
            operation_id=selected_operation_id,
            instrument_id=selected,
            fields=[
                InstrumentStateCommandField(
                    resource_id=selected,
                    capability_id=capability_id,
                    field_path=field_path,
                    value=(
                        value if isinstance(value, StateValue) else StateValue(value)
                    ),
                )
                for field_path, value in selected_values.items()
            ],
        )
        return self._client.apply_instrument_state(
            session.session_id,
            selected,
            command,
        )

    def collect(
        self,
        capability_id: str,
        *product_ids: str,
        instrument_id: str | None = None,
        operation_id: str | None = None,
    ) -> CollectReceipt:
        selected = self._selected_instrument_id(instrument_id)
        description = self.describe(selected)
        capability = next(
            (item for item in description.capabilities if item.id == capability_id),
            None,
        )
        if capability is None:
            raise ValueError(
                f"instrument {selected} has no capability {capability_id!r}"
            )
        products = {item.key: item for item in capability.products}
        selected_product_ids = product_ids or tuple(products)
        missing = tuple(
            product_id
            for product_id in selected_product_ids
            if product_id not in products
        )
        if missing:
            raise ValueError(
                f"capability {capability_id!r} has no products: {', '.join(missing)}"
            )
        session = self._require_session()
        command = CollectCommand(
            operation_id=_select_operation_id(
                operation_id,
                kind="collect",
                subject=selected,
            ),
            instrument_id=selected,
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id=product_id,
                    capability_id=capability_id,
                    unit=products[product_id].unit,
                    dtype=products[product_id].dtype,
                    dimensions=[
                        CollectAxisRequest(
                            id=axis.id,
                            kind=axis.kind,
                            size=axis.size,
                            unit=axis.unit,
                        )
                        for axis in products[product_id].axes
                        if axis.size is not None
                    ],
                )
                for product_id in selected_product_ids
            ],
        )
        return self._client.collect_instrument(
            session.session_id,
            selected,
            command,
        )

    def close(
        self,
    ) -> InstrumentSessionEndReceipt | None:
        return self._end(abort=False)

    def abort(
        self,
    ) -> InstrumentSessionEndReceipt | None:
        return self._end(abort=True)

    def _end(
        self,
        *,
        abort: bool,
    ) -> InstrumentSessionEndReceipt | None:
        if self._ended:
            return None
        session = self._session
        if session is None:
            self._ended = True
            return None
        receipt = (
            self._client.abort_instrument_session(session.session_id)
            if abort
            else self._client.close_instrument_session(session.session_id)
        )
        self._ended = True
        return receipt

    def _ensure_open(self) -> InstrumentSessionOpenReceipt:
        if self._ended:
            raise RuntimeError("instrument session is already closed")
        if self._session is None:
            self._session = self._client.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id=self._open_operation_id,
                    actor=self._actor,
                    instrument_ids=self._instrument_ids,
                )
            )
        return self._session

    def _require_session(self) -> InstrumentSessionOpenReceipt:
        return self._ensure_open()

    def _selected_instrument_id(self, instrument_id: str | None) -> str:
        if instrument_id is None:
            if len(self._instrument_ids) != 1:
                raise ValueError("multi-instrument sessions require an instrument_id")
            return self._instrument_ids[0]
        if instrument_id not in self._instrument_ids:
            raise ValueError(f"instrument {instrument_id!r} is not in this session")
        return instrument_id


def _operation_id(kind: str, subject: str) -> str:
    return f"interactive.{kind}.{subject}.{uuid4().hex}"


def _select_operation_id(
    requested: str | None,
    *,
    kind: str,
    subject: str,
) -> str:
    if requested is None:
        return _operation_id(kind, subject)
    if not requested:
        raise ValueError("instrument operation id must be non-empty")
    return requested


__all__ = [
    "InstrumentSessionHandle",
    "LabInstrumentOperations",
]
