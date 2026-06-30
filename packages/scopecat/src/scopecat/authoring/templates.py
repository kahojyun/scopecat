"""Global in-process experiment template registry."""

from scopecat.authoring._templates import (
    ExperimentDraft,
    ExperimentTemplate,
    TemplateRegistry,
)
from scopecat.authoring._templates import registry as _registry


def registry() -> TemplateRegistry:
    return _registry()


def register(experiment_template: ExperimentTemplate) -> ExperimentTemplate:
    return registry().register(experiment_template)


def get(template_id: str) -> ExperimentTemplate:
    return registry().get(template_id)


def list() -> tuple[ExperimentTemplate, ...]:  # noqa: A001
    return registry().list()


def build(template_id: str, **inputs: object) -> ExperimentDraft:
    return registry().build(template_id, **inputs)


__all__ = ["build", "get", "list", "register", "registry"]
