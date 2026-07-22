"""Pure validation and assembly for the fake realtime target."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from scopecat_quantum import (
    TargetArtifactId,
    TargetCompilerId,
    TargetId,
)

from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeArtifact,
    FakeRealtimeCompileRequest,
    FakeRealtimeTarget,
    instruction_payload,
)
from quantum_lab_demo.targets.fake_realtime.verifier import (
    verify_fake_realtime_request,
)


@dataclass(frozen=True, slots=True)
class FakeRealtimeCompiler:
    """Compile one finite microprogram without executing target effects."""

    id: TargetCompilerId
    target: FakeRealtimeTarget

    @property
    def target_id(self) -> TargetId:
        return self.target.id

    @property
    def capability_fingerprint(self) -> str:
        return self.target.capability_fingerprint

    def compile(self, request: FakeRealtimeCompileRequest) -> FakeRealtimeArtifact:
        """Verify the machine program, then fingerprint the executable."""

        program = request.program
        verified = verify_fake_realtime_request(request, self.target)
        payload = {
            "schema": "quantum_lab_demo.fake_realtime.artifact.v1",
            "target_id": self.target.id.value,
            "compiler_id": self.id.value,
            "capability_fingerprint": self.capability_fingerprint,
            "source_entry_ids": [item.value for item in request.source_entry_ids],
            "repetitions": request.repetitions,
            "program_id": program.id,
            "instructions": [
                instruction_payload(instruction) for instruction in program.instructions
            ],
            "result_layouts": [
                {
                    "entry_id": layout.entry_id.value,
                    "slot_id": {
                        "scope": list(layout.slot_id.scope),
                        "local_id": layout.slot_id.local_id,
                    },
                    "axes": [
                        {"id": axis.id, "size": axis.size} for axis in layout.axes
                    ],
                }
                for layout in request.result_layouts
            ],
            "realtime_result_provenance": [
                {
                    "result_id": {
                        "scope": list(item.result_id.scope),
                        "local_id": item.result_id.local_id,
                    },
                    "source_id": item.source_id.value,
                    "source_value_id": item.source_value_id.value,
                }
                for item in request.realtime_result_provenance
            ],
        }
        fingerprint = _fingerprint(payload)
        return FakeRealtimeArtifact(
            id=TargetArtifactId(
                f"fake-realtime-artifact-{fingerprint.removeprefix('sha256:')}"
            ),
            target_id=self.target.id,
            compiler_id=self.id,
            capability_fingerprint=self.capability_fingerprint,
            artifact_fingerprint=fingerprint,
            source_entry_ids=request.source_entry_ids,
            repetitions=request.repetitions,
            program=program,
            result_layouts=request.result_layouts,
            labels=verified.labels,
            realtime_result_provenance=request.realtime_result_provenance,
        )


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["FakeRealtimeCompiler"]
