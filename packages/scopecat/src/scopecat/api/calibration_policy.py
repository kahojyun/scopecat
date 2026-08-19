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
    """Exact historical capabilities plus active admission bindings.

    Omitting ``active`` infers one active binding only when every exact
    calibration definition has a single registered capability. Callers that
    retain multiple policies for the same definition must select the active
    policy explicitly; unselected policies remain available to drain cohorts
    that already pin them.
    """

    __slots__ = (
        "_active_bindings",
        "_active_by_calibration",
        "_capabilities",
        "_policies",
    )

    _policies: Mapping[
        CalibrationPublicationPolicyKey,
        CalibrationPublicationPolicyRegistration,
    ]
    _active_by_calibration: Mapping[
        str,
        CalibrationPublicationPolicyRegistration,
    ]
    _active_bindings: tuple[CalibrationPublicationPolicyRef, ...]
    _capabilities: tuple[CalibrationPublicationPolicyRef, ...]

    def __init__(
        self,
        policies: Iterable[CalibrationPublicationPolicyRegistration] = (),
        *,
        active: Iterable[CalibrationPublicationPolicyRef] | None = None,
    ) -> None:
        selected: dict[
            CalibrationPublicationPolicyKey,
            CalibrationPublicationPolicyRegistration,
        ] = {}
        by_calibration: dict[
            str,
            list[CalibrationPublicationPolicyRegistration],
        ] = {}
        calibration_id_by_policy_id: dict[str, str] = {}
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
            historical_calibration_id = calibration_id_by_policy_id.get(policy.id)
            if (
                historical_calibration_id is not None
                and policy.calibration.id != historical_calibration_id
            ):
                raise ValueError(
                    "historical versions of one calibration publication policy "
                    "must bind the same logical calibration definition"
                )
            selected[key] = policy
            calibration_id_by_policy_id[policy.id] = policy.calibration.id
            by_calibration.setdefault(
                policy.calibration.model_dump_json(),
                [],
            ).append(policy)

        ordered = dict(sorted(selected.items()))
        if active is None:
            ambiguous = tuple(
                candidates
                for candidates in by_calibration.values()
                if len(candidates) > 1
            )
            if ambiguous:
                rendered = ", ".join(
                    candidates[0].calibration.model_dump_json()
                    for candidates in ambiguous
                )
                raise ValueError(
                    "active calibration publication policy must be selected "
                    "explicitly for definitions with multiple capabilities: "
                    f"{rendered}"
                )
            active_policies = tuple(
                candidates[0] for candidates in by_calibration.values()
            )
        else:
            resolved_active: list[CalibrationPublicationPolicyRegistration] = []
            for ref in active:
                policy = ordered.get((ref.id, ref.version))
                if policy is None:
                    raise ValueError(
                        "active calibration publication policy is not a registered "
                        f"capability: {ref.id!r} version {ref.version!r}"
                    )
                if policy.ref != ref:
                    raise ValueError(
                        "active calibration publication policy does not match its "
                        "registered exact fingerprint/bindings"
                    )
                resolved_active.append(policy)
            active_policies = tuple(resolved_active)

        active_by_calibration: dict[
            str,
            CalibrationPublicationPolicyRegistration,
        ] = {}
        for policy in active_policies:
            calibration_key = policy.calibration.model_dump_json()
            existing = active_by_calibration.get(calibration_key)
            if existing is not None:
                raise ValueError(
                    "exact calibration definition has more than one active "
                    "publication policy "
                    f"({existing.id!r} {existing.version!r} and "
                    f"{policy.id!r} {policy.version!r})"
                )
            active_by_calibration[calibration_key] = policy

        self._policies = MappingProxyType(ordered)
        self._active_by_calibration = MappingProxyType(active_by_calibration)
        self._capabilities = tuple(policy.ref for policy in ordered.values())
        self._active_bindings = tuple(
            policy.ref for _, policy in sorted(active_by_calibration.items())
        )

    @property
    def capabilities(self) -> tuple[CalibrationPublicationPolicyRef, ...]:
        """Return every exact capability retained for cohort draining."""

        return self._capabilities

    @property
    def active_bindings(self) -> tuple[CalibrationPublicationPolicyRef, ...]:
        """Return deterministic exact policies selected for new admissions."""

        return self._active_bindings

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
        """Select the active policy bound to one exact calibration definition."""

        return self._active_by_calibration.get(ref.model_dump_json())


__all__ = [
    "MAX_CALIBRATION_PUBLICATION_POLICY_REGISTRY_SIZE",
    "CalibrationPublicationPolicyKey",
    "CalibrationPublicationPolicyRegistration",
    "CalibrationPublicationPolicyRegistry",
]
