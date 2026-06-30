from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "quantum"
NOTEBOOKS_DIR = EXAMPLE_ROOT / "notebooks"
SCRIPTS_DIR = EXAMPLE_ROOT / "scripts"
SUPPORT_DIR = EXAMPLE_ROOT / "support"


def test_quantum_examples_keep_notebook_first_learning_path() -> None:
    notebooks = [path.name for path in sorted(NOTEBOOKS_DIR.glob("*.py"))]
    readme = (EXAMPLE_ROOT / "README.md").read_text()

    assert notebooks == [
        "01_open_workspace.py",
        "02_define_experiment.py",
        "03_run_and_read_data.py",
        "04_manual_analysis.py",
        "05_promote_analysis_step.py",
        "06_review_candidate_and_rerun.py",
    ]
    for notebook in notebooks:
        assert f"`notebooks/{notebook}`" in readme
    assert "Workspace -> Experiment -> Run -> Data -> Analysis -> CandidateConfig" in (
        readme
    )


def test_quantum_support_package_stays_under_examples_boundary() -> None:
    workspace = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    support_project = tomllib.loads((SUPPORT_DIR / "pyproject.toml").read_text())
    members = workspace["tool"]["uv"]["workspace"]["members"]

    assert support_project["project"]["name"] == "quantum-lab-demo"
    assert "examples/quantum/support" in members
    assert "packages/scopecat-quantum" not in members
    assert "packages/quantum-lab-demo" not in members
    assert not (REPO_ROOT / "packages" / "scopecat-quantum").exists()
    assert not (REPO_ROOT / "packages" / "quantum-lab-demo").exists()


def test_script_examples_are_thin_workflow_wrappers() -> None:
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_from = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        function_names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }

        assert "scopecat" not in imported_modules
        assert all(module != "scopecat" for module in imported_from)
        assert {"run", "main"}.issubset(function_names)
        assert "quantum_lab_demo" in imported_from


def test_notebook_examples_are_top_level_cell_flows() -> None:
    for path in sorted(NOTEBOOKS_DIR.glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
            )
        ]
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_from = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }

        assert "# %%" in source
        assert definitions == []
        assert "dataclasses" not in imported_from
        assert "sys" not in imported_modules
        assert "scopecat" not in imported_modules
        assert "quantum_lab_demo.virtual_lab.provider" not in imported_from
        assert "native_instrument_provider" not in source
        assert "notebook_workspace" in source


def test_readmes_explain_how_to_copy_examples_into_a_lab() -> None:
    example_readme = (EXAMPLE_ROOT / "README.md").read_text()
    support_readme = (SUPPORT_DIR / "README.md").read_text()

    for phrase in {
        "When copying this example into a lab repository",
        "Change one-off analysis",
        "Promote repeated analysis",
        "Replace virtual hardware with a lab adapter",
    }:
        assert phrase in example_readme
    for phrase in {
        "analysis_calculations.py",
        "analysis_steps.py",
        "templates.py",
        "virtual_lab/provider.py",
    }:
        assert phrase in support_readme
