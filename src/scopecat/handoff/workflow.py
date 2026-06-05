"""Route-local handoff package writer/reader/inspection workflow."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff.inspect import write_inspection_artifact
from scopecat.handoff.package import HandoffPackage
from scopecat.handoff.read_only import open_package
from scopecat.handoff.writer import HandoffPackageWriteReceipt, write_package


@dataclass(frozen=True)
class HandoffPackageWorkflowRun:
    """Local workflow result for write -> read -> optional inspection."""

    write_receipt: HandoffPackageWriteReceipt
    package: HandoffPackage
    package_dir: str
    inspection_receipt: dict[str, Any] | None = None

    @property
    def package_id(self) -> str:
        return self.package.package_id

    @property
    def measurement_ids(self) -> tuple[str, ...]:
        return self.package.measurement_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_workflow_receipt",
            "classification": "package_written_opened_for_local_review",
            "steps": [
                "write_package",
                "open_package",
                *(["write_inspection_artifact"] if self.inspection_receipt is not None else []),
            ],
            "package": {
                "package_id": self.package.package_id,
                "display_name": self.package.display_name,
                "package_dir": self.package_dir,
                "measurement_ids": list(self.package.measurement_ids),
                "preview_classification": self.package.preview_classification,
                "finding_count": len(self.package.findings),
            },
            "write_receipt": self.write_receipt.to_dict(),
            "inspection_receipt": copy.deepcopy(self.inspection_receipt),
        }


def run_package_workflow(
    source: dict[str, Any],
    *,
    source_root: Path,
    package_root: Path,
    inspection_output_dir: Path | None = None,
    overwrite_inspection: bool = False,
) -> HandoffPackageWorkflowRun:
    """Write, open, and optionally inspect one directory-shaped handoff package."""

    write_receipt = write_package(
        source,
        source_root=source_root,
        package_root=package_root,
    )
    package_dir = Path(package_root) / write_receipt.package_dir
    package = open_package(package_dir)
    inspection_receipt = None
    if inspection_output_dir is not None:
        inspection_receipt = write_inspection_artifact(
            package,
            output_dir=inspection_output_dir,
            overwrite=overwrite_inspection,
        )
    return HandoffPackageWorkflowRun(
        write_receipt=write_receipt,
        package=package,
        package_dir=str(package_dir),
        inspection_receipt=inspection_receipt,
    )
