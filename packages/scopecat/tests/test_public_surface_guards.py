from __future__ import annotations

import ast
import re
from pathlib import Path

from pydantic import BaseModel

import scopecat as sc
import scopecat.experiments as experiments
import scopecat.models as models


def test_experiment_kernel_uses_results_facade_for_result_contracts() -> None:
    source_paths = [
        Path(experiments.__file__),
        Path(experiments.__file__).with_name("_planning_acquisition.py"),
    ]
    imported_modules = set[str]()
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text())
        imported_modules.update(
            imported for node in ast.walk(tree) for imported in _imported_modules(node)
        )

    assert "scopecat.results" in imported_modules
    assert "scopecat.models.measurement" not in imported_modules


def test_experiment_kernel_uses_final_record_mode_vocabulary() -> None:
    source = (
        Path(experiments.__file__).with_name("_planning_acquisition.py").read_text()
    )

    assert "AcquisitionRecordMode" in source
    assert "AcquisitionRecordGranularity" not in source


def test_core_source_does_not_use_removed_vocabulary() -> None:
    source_root = Path(sc.__file__).parent
    removed_terms = {
        "AcquisitionRecordGranularity",
        "experiment_type",
        "record_granularity",
        "require_binding_target",
        "require_target",
        "sweep_point",
        "sweep_point_count",
        "target_inputs",
    }

    offenders: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        source = path.read_text()
        found_terms = sorted(term for term in removed_terms if term in source)
        if found_terms:
            offenders[str(path.relative_to(source_root))] = found_terms

    assert not offenders


def test_core_source_does_not_use_domain_shaped_vocabulary() -> None:
    source_root = Path(sc.__file__).parent
    domain_terms = {
        "active_reset",
        "classifier",
        "crosstalk",
        "dac",
        "iq",
        "pulse",
        "quantum",
        "qubit",
        "readout",
        "waveform",
    }

    offenders: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        source = path.read_text().lower()
        found_terms = sorted(
            term
            for term in domain_terms
            if re.search(rf"\b{re.escape(term)}\b", source)
        )
        if found_terms:
            offenders[str(path.relative_to(source_root))] = found_terms

    assert not offenders


def test_core_modules_do_not_import_example_or_spike_packages() -> None:
    source_root = Path(sc.__file__).parent
    forbidden_prefixes = (
        "examples",
        "lab_system",
        "quantum_lab_demo",
        "scopecat_spike",
    )

    offenders: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        imported_modules = {
            imported for node in ast.walk(tree) for imported in _imported_modules(node)
        }
        forbidden_imports = sorted(
            imported
            for imported in imported_modules
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            )
        )
        if forbidden_imports:
            offenders[str(path.relative_to(source_root))] = forbidden_imports

    assert not offenders


def test_user_facing_docs_do_not_teach_retired_public_workflows() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    user_facing_docs = [
        repo_root / "README.md",
        repo_root / "docs" / "README.md",
        repo_root / "examples" / "README.md",
        repo_root / "examples" / "quantum" / "README.md",
        repo_root / "examples" / "quantum" / "support" / "README.md",
        repo_root / "docs" / "project-charter.md",
        repo_root / "docs" / "experiment-workflow.md",
        repo_root / "docs" / "gui-workbench-entry-contract.md",
        repo_root / "docs" / "domain-package-extraction-contract.md",
        repo_root / "docs" / "next-development-plan.md",
    ]
    retired_phrases = {
        "01_run_and_read_data.py",
        "02_manual_analysis_candidate.py",
        "03_promoted_analysis_step.py",
        "Open session",
        "processing and evaluation code",
        "processing and evaluation refs",
        "Run.evaluate",
        "Run.process",
        "lab_system",
        "packages/scopecat-lab-example",
        "readout_frequency_native.py",
        "readout_iq_native.py",
        "rerun_from_accepted",
        "run.evaluate(",
        "run.process(",
        "run_routine",
        "sc.session",
        "scopecat-lab-example",
        "scopecat_lab_example",
    }

    offenders: dict[str, list[str]] = {}
    for path in user_facing_docs:
        source = path.read_text()
        found_phrases = sorted(phrase for phrase in retired_phrases if phrase in source)
        if found_phrases:
            offenders[str(path.relative_to(repo_root))] = found_phrases

    assert not offenders


def test_public_model_facade_does_not_export_target_fields() -> None:
    exported_model_fields = {
        name: set(model.model_fields)
        for name in models.__all__
        if isinstance(model := getattr(models, name), type)
        and issubclass(model, BaseModel)
    }

    assert "ExperimentSpec" not in exported_model_fields
    assert "ParameterDefinition" not in exported_model_fields
    assert not {
        name: fields & {"target", "targets"}
        for name, fields in exported_model_fields.items()
        if fields & {"target", "targets"}
    }


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
