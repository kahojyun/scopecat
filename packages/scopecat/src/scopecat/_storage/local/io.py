"""Internal local storage I/O helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel


def read_model[TModel: BaseModel](path: Path, model_type: type[TModel]) -> TModel:
    return model_type.model_validate_json(path.read_text())


def write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.model_dump(mode="json"), indent=2) + "\n")


def write_model_atomic(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    write_model(temporary_path, model)
    temporary_path.replace(path)


def read_jsonl[TModel: BaseModel](path: Path, model_type: type[TModel]) -> list[TModel]:
    return [
        model_type.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as data_file:
        for record in records:
            data_file.write(record.model_dump_json() + "\n")


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if content and not content.endswith("\n"):
        content = f"{content}\n"
    path.write_text(content)
