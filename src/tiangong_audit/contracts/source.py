from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .platform import PlatformProjection, validate_platform_projection

SOURCE_SCHEMA_VERSION = "tiangong-audit-source-v1"

SOURCE_CHECK_STATUS_POLICY: dict[str, dict[str, Any]] = {
    "matched": {"default_severity": None, "allowed_severities": frozenset()},
    "not_applicable": {"default_severity": None, "allowed_severities": frozenset()},
    "conflict": {
        "default_severity": "blocking",
        "allowed_severities": frozenset({"blocking", "advisory"}),
    },
    "ambiguous": {
        "default_severity": "manual_review",
        "allowed_severities": frozenset({"manual_review", "advisory"}),
    },
    "not_found": {
        "default_severity": "manual_review",
        "allowed_severities": frozenset({"manual_review", "advisory"}),
    },
    "source_unavailable": {
        "default_severity": "input_gap",
        "allowed_severities": frozenset({"input_gap", "manual_review", "advisory"}),
    },
    "download_failed": {
        "default_severity": "input_gap",
        "allowed_severities": frozenset({"input_gap", "manual_review", "advisory"}),
    },
    "extraction_failed": {
        "default_severity": "input_gap",
        "allowed_severities": frozenset({"input_gap", "manual_review", "advisory"}),
    },
}


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
    severity: str | None = None
    platform: PlatformProjection | None = None

    def __post_init__(self) -> None:
        if self.platform is not None and not isinstance(
            self.platform, PlatformProjection
        ):
            self.platform = PlatformProjection.from_dict(self.platform)

    def resolved_severity(self) -> str | None:
        """Return the explicit impact, or the deterministic default for its status."""

        if self.severity is not None:
            return self.severity
        policy = SOURCE_CHECK_STATUS_POLICY.get(self.status)
        if policy is None:
            return None
        return policy["default_severity"]

    def to_dict(self) -> dict[str, Any]:
        checked_source_id = self.checked_source_id or self.source_ref_id
        matched_excerpt = self.matched_excerpt or self.evidence
        payload = {
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
        if self.severity is not None:
            payload["severity"] = self.severity
        if self.platform is not None:
            payload["platform"] = self.platform.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceCheck":
        check, errors = _parse_source_check(payload)
        if errors:
            raise ValueError("; ".join(errors))
        assert check is not None
        return check


_SOURCE_CHECK_FIELDS = {
    "schema_version",
    "field",
    "dataset_value",
    "source_ref_id",
    "checked_source_id",
    "status",
    "severity",
    "platform",
    "evidence",
    "matched_excerpt",
    "page",
    "notes",
    "rule_id",
    "confidence_reason",
    "extra",
}

_SOURCE_CHECK_REQUIRED_STRINGS = {"field", "dataset_value", "source_ref_id", "status"}
_SOURCE_CHECK_OPTIONAL_STRINGS = {
    "evidence",
    "notes",
    "rule_id",
    "checked_source_id",
    "matched_excerpt",
    "confidence_reason",
}


def _parse_source_check(payload: Any) -> tuple[SourceCheck | None, list[str]]:
    if not isinstance(payload, dict):
        return None, ["source check must be an object"]

    errors: list[str] = []
    unknown = set(payload) - _SOURCE_CHECK_FIELDS
    if unknown:
        errors.append(
            "source check contains unknown properties: " + ", ".join(sorted(unknown))
        )

    values: dict[str, Any] = {}
    for name in sorted(_SOURCE_CHECK_REQUIRED_STRINGS):
        if name not in payload:
            errors.append(f"source check {name} is required")
            continue
        value = payload[name]
        if not isinstance(value, str):
            errors.append(f"source check {name} must be a string")
        elif not value.strip():
            errors.append(f"source check {name} must be non-empty")
        else:
            values[name] = value

    for name in sorted(_SOURCE_CHECK_OPTIONAL_STRINGS):
        value = payload.get(name, "")
        if not isinstance(value, str):
            errors.append(f"source check {name} must be a string")
        else:
            values[name] = value

    if "schema_version" in payload:
        version = payload["schema_version"]
        if not isinstance(version, str):
            errors.append("source check schema_version must be a string")
        elif version != SOURCE_SCHEMA_VERSION:
            errors.append(f"unsupported source check schema_version {version!r}")

    severity: str | None = None
    if "severity" in payload:
        raw_severity = payload["severity"]
        if not isinstance(raw_severity, str):
            errors.append("source check severity must be a string")
        elif not raw_severity.strip():
            errors.append("source check severity must be non-empty")
        elif raw_severity != raw_severity.strip():
            errors.append("source check severity must not contain surrounding whitespace")
        else:
            severity = raw_severity

    platform: PlatformProjection | None = None
    if "platform" in payload:
        try:
            platform = PlatformProjection.from_dict(payload["platform"])
        except ValueError as exc:
            errors.append(f"source check platform: {exc}")

    page = payload.get("page")
    if page is not None and (not isinstance(page, int) or isinstance(page, bool)):
        errors.append("source check page must be an integer or null")

    extra = payload.get("extra", {})
    if not isinstance(extra, dict):
        errors.append("source check extra must be an object")

    if errors:
        return None, errors
    return (
        SourceCheck(
            field=values["field"],
            dataset_value=values["dataset_value"],
            source_ref_id=values["source_ref_id"],
            status=values["status"],
            evidence=values["evidence"],
            page=page,
            notes=values["notes"],
            rule_id=values["rule_id"],
            checked_source_id=values["checked_source_id"],
            matched_excerpt=values["matched_excerpt"],
            confidence_reason=values["confidence_reason"],
            extra=dict(extra),
            severity=severity,
            platform=platform,
        ),
        [],
    )


def validate_source_checks(payload: Any) -> list[str]:
    """Return readable contract errors for a field-level source-check list."""

    if not isinstance(payload, list):
        return ["source_checks must be an array"]

    errors: list[str] = []
    for index, item in enumerate(payload):
        prefix = f"source_checks[{index}]"
        check, structural_errors = _parse_source_check(item)
        if structural_errors:
            errors.extend(f"{prefix}: {error}" for error in structural_errors)
            continue
        assert check is not None

        policy = SOURCE_CHECK_STATUS_POLICY.get(check.status)
        if policy is None:
            errors.append(f"{prefix}: unknown source check status {check.status!r}")
            continue
        allowed = policy["allowed_severities"]

        resolved = check.resolved_severity()
        if resolved is None:
            if check.severity is not None:
                errors.append(
                    f"{prefix}: status {check.status!r} does not permit severity "
                    f"{check.severity!r}"
                )
        elif resolved not in allowed:
            errors.append(
                f"{prefix}: status {check.status!r} does not permit severity "
                f"{resolved!r}; expected one of {sorted(allowed)}"
            )

        if check.platform is None:
            continue
        if resolved is None:
            if check.platform.disposition != "internal_only":
                errors.append(
                    f"{prefix}: status {check.status!r} does not permit a "
                    "submitter-facing platform projection"
                )
            continue
        errors.extend(
            f"{prefix}: {error}"
            for error in validate_platform_projection(resolved, check.platform)
        )

    return errors
