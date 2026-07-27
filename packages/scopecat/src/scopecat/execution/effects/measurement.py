"""Collection effects and logical measurement-value accumulation."""

from __future__ import annotations

from collections.abc import Mapping

from scopecat.execution.effect_result import CoverageMeasurementObserver
from scopecat.execution.effects.compute import PointEffectState
from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.local.program import CollectOperation
from scopecat.execution.local.receipts import (
    collect_receipt_evidence,
    command_evidence,
    validate_readback,
)
from scopecat.measurements.points import RunPoint
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.records.instrument import InstrumentReadback
from scopecat.sdk.instruments.contracts import InstrumentDriver
from scopecat.sdk.runtime_problems import contextualize_problems


class MeasurementEffectExecutor:
    """Collect, validate, and checkpoint logical measurement candidates."""

    def __init__(
        self,
        *,
        drivers: Mapping[str, InstrumentDriver],
        journal: JournaledEffectBoundary,
        coverage_observer: CoverageMeasurementObserver | None,
    ) -> None:
        self.drivers = drivers
        self.journal = journal
        self.coverage_observer = coverage_observer
        self.values: list[MeasurementValueCandidate] = []

    def commit_coverage(
        self,
        points: tuple[RunPoint, ...],
    ) -> None:
        if self.coverage_observer is None:
            return
        point_index_set = frozenset(point.ordinal for point in points)
        candidates = tuple(
            candidate
            for candidate in self.values
            if candidate.logical_point_id.logical_ordinal in point_index_set
        )
        self.coverage_observer(points, candidates)
        self.values[:] = (
            candidate
            for candidate in self.values
            if candidate.logical_point_id.logical_ordinal not in point_index_set
        )

    def execute(
        self,
        frame: PointEffectState,
        operation: CollectOperation,
    ) -> bool:
        command = operation.command.model_copy(deep=True)
        command_details = command_evidence(command)
        entry = self.journal.entry(
            operation_id=operation.operation_id,
            stage="collect",
            effect="acquisition",
            state="started",
            point_index=frame.point_index,
            instrument_id=operation.instrument_id,
            evidence={
                "request_count": len(operation.command.requests),
                "product_ids": [item.id for item in operation.command.requests],
                **command_details,
            },
        )
        receipt = self.journal.invoke(
            entry,
            lambda: self.drivers[operation.instrument_id].collect(command),
            unknown_code="instrument_collect_unknown",
            unknown_message=(
                "instrument collection outcome is unknown for "
                f"{operation.instrument_id}"
            ),
        )
        if receipt is None:
            return False
        receipt_evidence = collect_receipt_evidence(receipt)
        accepted, receipt_problems = self.journal.accept_receipt(
            entry,
            status=receipt.status,
            success_status="collected",
            problems=receipt.problems,
            evidence={**entry.evidence, **receipt_evidence},
        )
        if not accepted:
            return False
        assert receipt.readback is not None
        readback = receipt.readback
        validation_problems = contextualize_problems(
            validate_readback(operation, readback),
            run_id=self.journal.run_id,
            operation_id=operation.operation_id,
            point_index=frame.point_index,
            instrument_id=operation.instrument_id,
        )
        operation_problems = (*receipt_problems, *validation_problems)
        self.journal.problems.extend(validation_problems)
        if not bool(operation_problems):
            self._merge_readback(frame, operation, readback)
        failed = bool(operation_problems)
        self.journal.commit_after_effect(
            entry.model_copy(
                update={
                    "state": "failed" if failed else "completed",
                    "problems": operation_problems,
                    "evidence": {
                        **entry.evidence,
                        **receipt_evidence,
                        "value_count": len(readback.values),
                    },
                }
            )
        )
        return not failed

    def _merge_readback(
        self,
        frame: PointEffectState,
        operation: CollectOperation,
        readback: InstrumentReadback,
    ) -> None:
        bindings = {
            binding.provider_key: binding for binding in operation.result_bindings
        }
        for provider_key, value in readback.values.items():
            binding = bindings.get(provider_key)
            if binding is None:
                self.journal.problems.append(
                    self.journal.problem(
                        "instrument_unexpected_product",
                        (
                            f"instrument {operation.instrument_id} returned "
                            f"unexpected product {provider_key}"
                        ),
                        operation_id=operation.operation_id,
                        point_index=frame.point_index,
                        instrument_id=operation.instrument_id,
                    )
                )
                continue
            for product_use_id in binding.product_use_ids:
                if product_use_id in frame.product_use_ids:
                    self.journal.problems.append(
                        self.journal.problem(
                            "instrument_duplicate_product_use",
                            "point received more than one result for logical "
                            f"product use {product_use_id.value}",
                            operation_id=operation.operation_id,
                            point_index=frame.point_index,
                            instrument_id=operation.instrument_id,
                        )
                    )
                    continue
                frame.product_use_ids.add(product_use_id)
                self.values.append(
                    MeasurementValueCandidate(
                        logical_point_id=frame.logical_id,
                        product_use_id=product_use_id,
                        value=value,
                    )
                )
