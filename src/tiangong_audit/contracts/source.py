from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SOURCE_SCHEMA_VERSION = "tiangong-audit-source-v1"


@dataclass(slots=True)
class SourceRef:
    """Reference to a source artifact mentioned by a dataset."""

    source_id: str = ""
    version: str = ""
    uri: str = ""
    url: str = ""
    path: str = ""
    label: str = ""
    source_type: str = ""
    location: str = ""

    def locator(self) -> str:
        return self.url or self.path or self.uri

    def stable_id(self) -> str:
        return self.source_id or self.locator() or self.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "source_id": self.source_id,
            "version": self.version,
            "uri": self.uri,
            "url": self.url,
            "path": self.path,
            "label": self.label,
            "source_type": self.source_type,
            "location": self.location,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceRef":
        return cls(
            source_id=str(payload.get("source_id") or ""),
            version=str(payload.get("version") or ""),
            uri=str(payload.get("uri") or ""),
            url=str(payload.get("url") or ""),
            path=str(payload.get("path") or ""),
            label=str(payload.get("label") or ""),
            source_type=str(payload.get("source_type") or ""),
            location=str(payload.get("location") or ""),
        )


@dataclass(slots=True)
class SourceArtifact:
    """Downloaded and extracted representation of one source reference."""

    ref: SourceRef
    status: str = "pending"
    file_path: str = ""
    content_type: str = ""
    sha256: str = ""
    downloaded_at: str = ""
    extracted_text_path: str = ""
    error: str = ""
    related_artifact_requirements: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "ref": self.ref.to_dict(),
            "status": self.status,
            "file_path": self.file_path,
            "content_type": self.content_type,
            "sha256": self.sha256,
            "downloaded_at": self.downloaded_at,
            "extracted_text_path": self.extracted_text_path,
            "error": self.error,
            "related_artifact_requirements": list(self.related_artifact_requirements),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceArtifact":
        return cls(
            ref=SourceRef.from_dict(dict(payload.get("ref") or {})),
            status=str(payload.get("status") or "pending"),
            file_path=str(payload.get("file_path") or ""),
            content_type=str(payload.get("content_type") or ""),
            sha256=str(payload.get("sha256") or ""),
            downloaded_at=str(payload.get("downloaded_at") or ""),
            extracted_text_path=str(payload.get("extracted_text_path") or ""),
            error=str(payload.get("error") or ""),
            related_artifact_requirements=list(
                payload.get("related_artifact_requirements") or []
            ),
        )


@dataclass(slots=True)
class SourceCheck:
    """Field-level comparison between dataset content and source evidence."""

    field: str
    dataset_value: str
    source_ref_id: str
    status: str
    evidence: str = ""
    page: int | None = None
    notes: str = ""
    rule_id: str = ""
    checked_source_id: str = ""
    matched_excerpt: str = ""
    confidence_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        checked_source_id = self.checked_source_id or self.source_ref_id
        matched_excerpt = self.matched_excerpt or self.evidence
        return {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "field": self.field,
            "dataset_value": self.dataset_value,
            "source_ref_id": self.source_ref_id,
            "checked_source_id": checked_source_id,
            "status": self.status,
            "evidence": self.evidence,
            "matched_excerpt": matched_excerpt,
            "page": self.page,
            "notes": self.notes,
            "rule_id": self.rule_id,
            "confidence_reason": self.confidence_reason,
            "extra": dict(self.extra),
        }
