"""Client-side assembly of concrete daemon hardware batches."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from scopecat.execution.effects.boundary import EffectBoundary
from scopecat.execution.effects.compute import PointEffectState
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    InvokeOperation,
)
from scopecat.execution.program import RunCoverageEffect
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.state import PayloadRef
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.sdk.instruments.execution import (
    RunHardwareAction,
    RunHardwareApply,
    RunHardwareBatch,
    RunHardwareCollect,
    RunHardwareCollectBinding,
    RunHardwareInvoke,
    RunInstrumentHost,
)
from scopecat.sdk.runtime_problems import contextualize_problems


class HardwareEffectExecutor:
    """Submit maximal concrete hardware blocks to the daemon."""

    def __init__(
        self,
        *,
        instruments: RunInstrumentHost,
        problems: EffectBoundary,
    ) -> None:
        self.instruments = instruments
        self.problems = problems
        self.values: list[MeasurementValueCandidate] = []

    def execute(
        self,
        effects: Sequence[RunCoverageEffect],
        *,
        frame_for: Callable[[int], PointEffectState],
    ) -> bool:
        actions = tuple(
            _action(effect, frame=frame_for(effect.point_index)) for effect in effects
        )
        return self._execute_actions(actions, frame_for=frame_for)

    def execute_success_state(
        self,
        operations: Sequence[ApplyStateOperation],
    ) -> bool:
        """Apply normal-completion state without assigning it to a point."""

        actions = tuple(
            RunHardwareApply(
                effect_id=operation.operation_id,
                instrument_id=operation.instrument_id,
                assignments=tuple(
                    target.command_assignment(resource_id=operation.instrument_id)
                    for target in operation.targets
                ),
            )
            for operation in operations
        )
        return self._execute_actions(actions, frame_for=None)

    def _execute_actions(
        self,
        actions: tuple[RunHardwareAction, ...],
        *,
        frame_for: Callable[[int], PointEffectState] | None,
    ) -> bool:
        if not actions:
            return True
        batch = RunHardwareBatch(
            operation_id="hardware."
            + stable_content_hash(
                [
                    action.model_dump(
                        mode="json",
                        exclude={"payloads": {"__all__": {"body"}}},
                    )
                    for action in actions
                ]
            ),
            actions=actions,
        )
        try:
            receipt = self.instruments.execute(batch)
        except Exception as error:
            self.problems.indeterminate = True
            self.problems.problems.append(
                self.problems.problem_from_exception(
                    "hardware_batch_unknown",
                    "daemon hardware batch outcome is unknown",
                    error,
                    operation_id=batch.operation_id,
                )
            )
            return False
        if receipt.operation_id != batch.operation_id:
            self.problems.indeterminate = True
            self.problems.problems.append(
                self.problems.problem(
                    "hardware_batch_receipt_mismatch",
                    "daemon returned a receipt for another hardware batch",
                    operation_id=batch.operation_id,
                )
            )
            return False
        self.problems.problems.extend(
            contextualize_problems(
                receipt.problems,
                run_id=self.problems.run_id,
                operation_id=batch.operation_id,
            )
        )
        self.problems.indeterminate = (
            self.problems.indeterminate or receipt.indeterminate
        )
        if receipt.problems:
            return False
        for value in receipt.values:
            if frame_for is None:
                self.problems.problems.append(
                    self.problems.problem(
                        "instrument_success_state_returned_value",
                        "normal-completion state application returned "
                        "an unexpected measurement",
                        operation_id=batch.operation_id,
                    )
                )
                continue
            if value.point_index is None:
                self.problems.problems.append(
                    self.problems.problem(
                        "instrument_measurement_missing_point",
                        "experiment hardware result has no logical point index",
                        operation_id=batch.operation_id,
                    )
                )
                continue
            frame = frame_for(value.point_index)
            product_use_id = ProductUseId(value.value_id)
            if product_use_id in frame.product_use_ids:
                self.problems.problems.append(
                    self.problems.problem(
                        "instrument_duplicate_product_use",
                        "point received more than one result for a logical product use",
                        operation_id=batch.operation_id,
                        point_index=value.point_index,
                    )
                )
                continue
            frame.product_use_ids.add(product_use_id)
            self.values.append(
                MeasurementValueCandidate(
                    logical_point_id=frame.logical_id,
                    product_use_id=product_use_id,
                    value=value.value,
                    evidence=value.evidence,
                )
            )
        return not self.problems.problems


def _action(
    effect: RunCoverageEffect,
    *,
    frame: PointEffectState,
) -> RunHardwareAction:
    operation = effect.operation
    if isinstance(operation, ApplyStateOperation):
        assignments = tuple(
            target.command_assignment(resource_id=operation.instrument_id)
            for target in operation.targets
        )
        return RunHardwareApply(
            effect_id=operation.operation_id,
            point_index=effect.point_index,
            instrument_id=operation.instrument_id,
            assignments=assignments,
        )
    if isinstance(operation, InvokeOperation):
        payload_ids = {
            value.payload_id
            for argument in operation.arguments
            if isinstance((value := argument.value.root), PayloadRef)
        }
        return RunHardwareInvoke(
            effect_id=operation.effect_id,
            point_index=effect.point_index,
            instrument_id=operation.instrument_id,
            resource_id=operation.resource_id,
            interface_id=operation.interface_id,
            component_path=operation.component_path,
            operation_id=operation.operation_id,
            arguments=operation.arguments,
            payloads={
                payload_id: frame.payloads[payload_id]
                for payload_id in payload_ids
                if payload_id in frame.payloads
            },
            entity_ids=operation.entity_ids,
            channel_bindings=operation.channel_bindings,
        )
    if isinstance(operation, CollectOperation):
        command = operation.command
        return RunHardwareCollect(
            effect_id=operation.operation_id,
            point_index=effect.point_index,
            instrument_id=operation.instrument_id,
            point_count=command.point_count,
            requests=tuple(command.requests),
            bindings=tuple(
                RunHardwareCollectBinding(
                    request_id=binding.request_id,
                    value_ids=tuple(
                        product_use_id.value
                        for product_use_id in binding.product_use_ids
                    ),
                )
                for binding in operation.result_bindings
            ),
        )
    raise TypeError(f"operation is not a hardware effect: {type(operation).__name__}")


__all__ = ["HardwareEffectExecutor"]
