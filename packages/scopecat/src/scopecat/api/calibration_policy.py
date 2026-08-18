"""Lightweight exact registry declarations for calibration publication policy."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Protocol, override

from scopecat.automation.calibrations import (
    CalibrationDefinitionRef,
    CalibrationPublicationPolicyRef,
)
from scopecat.config.registry.records import ConfigCompositionPolicyRef
from scopecat.records.content import Sha256ContentHash

MAX_CALIBRATION_PUBLICATION_POLICY_REGISTRY_SIZE = 200

type CalibrationPublicationPolicyKey = tuple[str, str]


class CalibrationPublicationPolicyRegistration(Protocol):
    """Lightweight exact identity retained by project application composition."""

    @property
    def id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def fingerprint(self) -> Sha256ContentHash: ...

    @property
    def calibration(self) -> CalibrationDefinitionRef: ...

    @property
    def composition_policy(self) -> ConfigCompositionPolicyRef: ...

    @property
    def actor(self) -> str: ...

    @property
    def note(self) -> str: ...

    @property
    def ref(self) -> CalibrationPublicationPolicyRef: ...


class CalibrationPublicationPolicyRegistry(
    Mapping[CalibrationPublicationPolicyKey, CalibrationPublicationPolicyRegistration]
):
    """Immutable exact-version registry that retains historical policies."""

    __slots__ = ("_by_calibration", "_policies", "_refs")

    _policies: Mapping[
        CalibrationPublicationPolicyKey,
        CalibrationPublicationPolicyRegistration,
    ]
    _by_calibration: Mapping[str, CalibrationPublicationPolicyRegistration]
    _refs: tuple[CalibrationPublicationPolicyRef, ...]

    def __init__(
        self,
        policies: Iterable[CalibrationPublicationPolicyRegistration] = (),
    ) -> None:
        selected: dict[
            CalibrationPublicationPolicyKey,
            CalibrationPublicationPolicyRegistration,
        ] = {}
        by_calibration: dict[str, CalibrationPublicationPolicyRegistration] = {}
        history_by_id: dict[str, tuple[str, set[str]]] = {}
        for policy in policies:
            expected_ref = CalibrationPublicationPolicyRef(
                id=policy.id,
                version=policy.version,
                fingerprint=policy.fingerprint,
                calibration=policy.calibration,
                composition_policy=policy.composition_policy,
            )
            if policy.ref != expected_ref:
                raise ValueError(
                    "calibration publication policy ref does not match its "
                    "declared exact identity"
                )
            key = (policy.id, policy.version)
            if key in selected:
                raise ValueError(
                    f"calibration publication policy {policy.id!r} version "
                    f"{policy.version!r} is registered more than once"
                )
            if len(selected) >= MAX_CALIBRATION_PUBLICATION_POLICY_REGISTRY_SIZE:
                raise ValueError(
                    "calibration publication policy registry supports at most "
                    f"{MAX_CALIBRATION_PUBLICATION_POLICY_REGISTRY_SIZE} policies"
                )
            calibration_key = policy.calibration.model_dump_json()
            if calibration_key in by_calibration:
                existing = by_calibration[calibration_key]
                raise ValueError(
                    "exact calibration definition is bound to more than one "
                    "publication policy "
                    f"({existing.id!r} {existing.version!r} and "
                    f"{policy.id!r} {policy.version!r})"
                )
            historical = history_by_id.get(policy.id)
            if historical is not None and (
                policy.calibration.id != historical[0]
                or policy.calibration.version in historical[1]
            ):
                raise ValueError(
                    "historical versions of one calibration publication policy "
                    "must bind distinct versions of the same calibration definition"
                )
            selected[key] = policy
            by_calibration[calibration_key] = policy
            if historical is None:
                history_by_id[policy.id] = (
                    policy.calibration.id,
                    {policy.calibration.version},
                )
            else:
                historical[1].add(policy.calibration.version)

        ordered = dict(sorted(selected.items()))
        self._policies = MappingProxyType(ordered)
        self._by_calibration = MappingProxyType(by_calibration)
        self._refs = tuple(policy.ref for policy in ordered.values())

    @property
    def refs(self) -> tuple[CalibrationPublicationPolicyRef, ...]:
        """Return the deterministic exact capabilities exposed to discovery."""

        return self._refs

    @override
    def __getitem__(
        self,
        key: CalibrationPublicationPolicyKey,
    ) -> CalibrationPublicationPolicyRegistration:
        return self._policies[key]

    @override
    def __iter__(self) -> Iterator[CalibrationPublicationPolicyKey]:
        return iter(self._policies)

    @override
    def __len__(self) -> int:
        return len(self._policies)

    def require(
        self,
        id: str,
        version: str,
    ) -> CalibrationPublicationPolicyRegistration:
        try:
            return self._policies[(id, version)]
        except KeyError as error:
            raise LookupError(
                f"no calibration publication policy {id!r} version "
                f"{version!r} is registered"
            ) from error

    def resolve(
        self,
        ref: CalibrationPublicationPolicyRef,
    ) -> CalibrationPublicationPolicyRegistration:
        policy = self.require(ref.id, ref.version)
        if policy.ref != ref:
            raise ValueError(
                f"calibration publication policy {ref.id!r} version "
                f"{ref.version!r} does not match its exact fingerprint/bindings"
            )
        return policy

    def for_calibration(
        self,
        ref: CalibrationDefinitionRef,
    ) -> CalibrationPublicationPolicyRegistration | None:
        """Select the unique policy bound to one exact calibration definition."""

        return self._by_calibration.get(ref.model_dump_json())


__all__ = [
    "MAX_CALIBRATION_PUBLICATION_POLICY_REGISTRY_SIZE",
    "CalibrationPublicationPolicyKey",
    "CalibrationPublicationPolicyRegistration",
    "CalibrationPublicationPolicyRegistry",
]
