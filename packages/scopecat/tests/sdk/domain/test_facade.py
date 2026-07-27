"""Public execution-domain SDK facade contracts."""

from __future__ import annotations

import scopecat.sdk.domain as domain

_DOMAIN_ADAPTER_CONTRACTS = {
    "DomainBatchInputs",
    "DomainBatchRequest",
    "DomainFetchReceipt",
    "DomainFetchResult",
    "DomainInvocationSpec",
    "DomainMappedResult",
    "DomainResultValue",
    "DomainSubmitReceipt",
}


def test_domain_facade_exports_curated_adapter_contracts() -> None:
    assert set(domain.__all__) >= _DOMAIN_ADAPTER_CONTRACTS
