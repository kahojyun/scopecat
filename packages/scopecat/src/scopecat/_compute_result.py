"""Private symbolic references to point-local compute results."""

from pydantic import BaseModel, ConfigDict, field_validator

from scopecat._compiler.ids import NodeId


class ComputeResultRef(BaseModel):
    """Internal symbolic reference to one point-local compute result."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    node_id: NodeId

    @field_validator("node_id", mode="before")
    @classmethod
    def coerce_root_node_id(cls, value: object) -> object:
        return NodeId(local_id=value) if isinstance(value, str) else value


__all__ = ["ComputeResultRef"]
