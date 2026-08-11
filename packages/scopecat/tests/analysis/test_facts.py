from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, field_serializer

import scopecat as sc
from scopecat.analysis.facts import ANALYSIS_FACT_SCHEMA_CODEC


@dataclass(frozen=True, slots=True)
class _FitSummary:
    resonance: sc.Quantity
    quality: float
    label: str = "fit"


@dataclass(frozen=True, slots=True)
class _RenamedFitSummary:
    resonance: sc.Quantity
    quality: float
    label: str = "renamed default"


@dataclass(frozen=True, slots=True)
class _DifferentFitSummary:
    resonance: sc.Quantity
    converged: bool


class _DescribedFit(BaseModel):
    quality: float = Field(description="First description")


class _RedescribedFit(BaseModel):
    quality: float = Field(description="Changed documentation only")


class _CustomSerializedFit(BaseModel):
    quality: float

    @field_serializer("quality")
    def serialize_quality(self, value: float) -> str:
        return str(value)


def test_fact_schema_hash_uses_stable_scopecat_structure() -> None:
    original = sc.AnalysisFactSchema("tests.fit.v1", _FitSummary)
    renamed = sc.AnalysisFactSchema("tests.fit.v1", _RenamedFitSummary)

    assert original.schema_codec == ANALYSIS_FACT_SCHEMA_CODEC
    assert original.schema_hash == renamed.schema_hash
    assert original.structure == {
        "type": "object",
        "fields": {
            "resonance": {
                "type": "quantity",
                "value": {"type": "float"},
                "unit": {"type": "string"},
            },
            "quality": {"type": "float"},
            "label": {"type": "string"},
        },
    }


def test_fact_schema_hash_ignores_pydantic_documentation() -> None:
    described = sc.AnalysisFactSchema("tests.described.v1", _DescribedFit)
    redescribed = sc.AnalysisFactSchema("tests.described.v1", _RedescribedFit)

    assert described.schema_hash == redescribed.schema_hash


def test_fact_schema_hash_changes_with_the_canonical_shape() -> None:
    original = sc.AnalysisFactSchema("tests.fit.v1", _FitSummary)
    changed = sc.AnalysisFactSchema("tests.fit.v1", _DifferentFitSummary)

    assert original.schema_hash != changed.schema_hash


def test_fact_schema_rejects_serializer_output_outside_its_structure() -> None:
    schema = sc.AnalysisFactSchema("tests.custom-serializer.v1", _CustomSerializedFit)

    with pytest.raises(TypeError, match=r"\$fact\.quality.*float"):
        schema.encode(_CustomSerializedFit(quality=0.9))


def test_fact_schema_ignores_analysis_projection_metadata() -> None:
    @dataclass(frozen=True, slots=True)
    class First:
        value: Annotated[float, sc.AnalysisField(label="First label")]

    @dataclass(frozen=True, slots=True)
    class Second:
        value: Annotated[float, sc.AnalysisField(label="Second label", unit="ratio")]

    assert (
        sc.AnalysisFactSchema("tests.value.v1", First).schema_hash
        == sc.AnalysisFactSchema("tests.value.v1", Second).schema_hash
    )
