"""Private symbolic references to point-local compute results."""

from pydantic import BaseModel, ConfigDict, Field


class ComputeResultRef(BaseModel):
    """Internal symbolic reference to one point-local compute result."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    node_id: str = Field(min_length=1)


__all__ = ["ComputeResultRef"]
