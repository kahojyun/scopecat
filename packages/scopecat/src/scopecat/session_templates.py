"""Template browsing facade for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scopecat.authoring import (
    ExperimentDraft,
    ExperimentTemplate,
    TemplateRegistry,
    templates,
)
from scopecat.workflows import PreviewExperimentResult


class TemplateSession(Protocol):
    def preview(
        self,
        experiment: ExperimentDraft,
    ) -> PreviewExperimentResult: ...


@dataclass(frozen=True)
class TemplateBrowser:
    session: TemplateSession
    registry: TemplateRegistry | None = None

    @property
    def selected_registry(self) -> TemplateRegistry:
        return self.registry or templates.registry()

    def list(self, *, category: str | None = None) -> tuple[ExperimentTemplate, ...]:
        selected = self.selected_registry.list()
        if category is None:
            return selected
        return tuple(
            experiment_template
            for experiment_template in selected
            if experiment_template.metadata.get("category") == category
        )

    def get(self, template_id: str) -> ExperimentTemplate:
        return self.selected_registry.get(template_id)

    def build(self, template_id: str, **inputs: object) -> ExperimentDraft:
        return self.selected_registry.build(template_id, **inputs)

    def preview(self, draft: ExperimentDraft) -> PreviewExperimentResult:
        return self.session.preview(draft)


__all__ = ["TemplateBrowser"]
