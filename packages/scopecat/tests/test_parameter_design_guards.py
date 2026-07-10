from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
DESIGN_ROOTS = (
    REPO_ROOT / "packages" / "scopecat" / "src",
    REPO_ROOT / "examples",
    REPO_ROOT / "fixtures",
    REPO_ROOT / "docs",
    REPO_ROOT / "README.md",
)
SOURCE_SUFFIXES = {".json", ".md", ".py", ".toml", ".yaml", ".yml"}
FORBIDDEN_PARAMETER_VOCABULARY = (
    r"\bParameterState\b",
    r"\bParameterPatch\b",
    r"\bParameterPatchSpec\b",
    r"\bParameterScanPatchIntent\b",
    r"\bParameterChangeSet\b",
    r"\bParameterScalarType\b",
    r"\bParameterScalarValue\b",
    r"\bParameterTable\b",
    r"\bParameterTableColumn\b",
    r"\bParameterTableDefinition\b",
    r"\bParameterValue\b",
    r"\bscalar_definitions\b",
    r"\btable_definitions\b",
    r"\bscalar_values\b",
    r"\bparameter_state\b",
    r"\bparameter_tables\b",
    r"\bparameter_patches\b",
    r"\bset_param\b",
    r"\bupdate_param_rows\b",
    r"\binsert_param_rows\b",
    r"\bdelete_param_rows\b",
    r"\bapply_parameter_patches\b",
    r"\bdiff_parameter_states\b",
    r"\bparameter_change_set\b",
)


def test_legacy_parameter_state_and_patch_vocabulary_does_not_return() -> None:
    findings: list[str] = []
    patterns = tuple(re.compile(pattern) for pattern in FORBIDDEN_PARAMETER_VOCABULARY)
    for path in _design_files():
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}"
                )

    assert findings == [], "legacy parameter design vocabulary found:\n" + "\n".join(
        findings
    )


def _design_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root in DESIGN_ROOTS:
        if root.is_file():
            files.append(root)
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in SOURCE_SUFFIXES
        )
    return tuple(sorted(files))
