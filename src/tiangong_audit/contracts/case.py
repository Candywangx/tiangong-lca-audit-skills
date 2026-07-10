from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CASE_SCHEMA_VERSION = "tiangong-audit-case-v1"

DEFAULT_CASE_STEPS: dict[str, bool] = {
    "fetched": False,
    "normalized": False,
    "sources_resolved": False,
    "sources_downloaded": False,
    "source_verified": False,
    "prechecked": False,
    "agent_reviewed": False,
    "semantic_reviewed": False,
    "reported": False,
    "platform_written": False,
}


@dataclass(slots=True)
class AuditCaseManifest:
    """Persistent manifest for one review task in cases/."""

    review_id: str
    batch_id: str
    dataset_id: str = ""
    version: str = ""
    dataset_type: str = ""
    name_zh: str = ""
    name_en: str = ""
    status: str = "initialized"
    conclusion: str = ""
    platform_state: str = ""
    case_dir: str = ""
    report: str = ""
    steps: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_CASE_STEPS))
    artifacts: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CASE_SCHEMA_VERSION,
            "review_id": self.review_id,
            "batch_id": self.batch_id,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "dataset_type": self.dataset_type,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "status": self.status,
            "conclusion": self.conclusion,
            "platform_state": self.platform_state,
            "case_dir": self.case_dir,
            "report": self.report,
            "steps": {**DEFAULT_CASE_STEPS, **self.steps},
            "artifacts": dict(self.artifacts),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuditCaseManifest":
        if payload.get("schema_version") != CASE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported case manifest schema: {payload.get('schema_version')}"
            )
        return cls(
            review_id=str(payload.get("review_id") or ""),
            batch_id=str(payload.get("batch_id") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            version=str(payload.get("version") or ""),
            dataset_type=str(payload.get("dataset_type") or ""),
            name_zh=str(payload.get("name_zh") or ""),
            name_en=str(payload.get("name_en") or ""),
            status=str(payload.get("status") or "initialized"),
            conclusion=str(payload.get("conclusion") or ""),
            platform_state=str(payload.get("platform_state") or ""),
            case_dir=str(payload.get("case_dir") or ""),
            report=str(payload.get("report") or ""),
            steps={**DEFAULT_CASE_STEPS, **dict(payload.get("steps") or {})},
            artifacts=dict(payload.get("artifacts") or {}),
            notes=list(payload.get("notes") or []),
        )

    def set_step(self, step: str, value: bool = True) -> None:
        if step not in DEFAULT_CASE_STEPS:
            raise ValueError(f"Unknown case step: {step}")
        self.steps[step] = value

    def index_record(self) -> dict[str, Any]:
        return {
            "schema_version": CASE_SCHEMA_VERSION,
            "review_id": self.review_id,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "dataset_type": self.dataset_type,
            "name_zh": self.name_zh,
            "status": self.status,
            "conclusion": self.conclusion,
            "platform_state": self.platform_state,
            "batch_id": self.batch_id,
            "case_dir": self.case_dir,
            "report": self.report,
        }
