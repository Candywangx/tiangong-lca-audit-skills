from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .finding import VALID_SEVERITIES
from .platform import PlatformProjection, validate_platform_projection

AGENT_FINDINGS_SCHEMA_VERSION_V1 = "tiangong-audit-agent-findings-v1"
AGENT_FINDINGS_SCHEMA_VERSION = "tiangong-audit-agent-findings-v2"
SUPPORTED_AGENT_FINDINGS_SCHEMA_VERSIONS = {
    AGENT_FINDINGS_SCHEMA_VERSION_V1,
    AGENT_FINDINGS_SCHEMA_VERSION,
}
VALID_VERDICTS = ("pass", "fail", "cannot_judge", "not_applicable")

_TOP_LEVEL_FIELDS_V1 = {
    "schema_version",
    "review_id",
    "dataset_id",
    "dataset_type",
    "reviewed_by",
    "reviewed_at",
    "source_documents_read",
    "rule_reviews",
    "additional_findings",
}
_TOP_LEVEL_FIELDS_V2 = _TOP_LEVEL_FIELDS_V1 | {"platform_overrides"}
_RULE_REVIEW_FIELDS_V1 = {
    "rule_id",
    "verdict",
    "location",
    "evidence",
    "judgment",
    "suggestion",
    "severity",
    "evidence_refs",
}
_RULE_REVIEW_FIELDS_V2 = _RULE_REVIEW_FIELDS_V1 | {"platform"}
_ADDITIONAL_FINDING_FIELDS_V1 = {
    "rule_id",
    "severity",
    "location",
    "evidence",
    "judgment",
    "suggestion",
    "source",
    "evidence_refs",
}
_ADDITIONAL_FINDING_FIELDS_V2 = _ADDITIONAL_FINDING_FIELDS_V1 | {"platform"}

# Single source of truth for judgment rules that the Agent must explicitly
# review before a case can conclude "通过". The rule engine surfaces this list
# in precheck output and semantic-review enforces coverage.
REQUIRED_AGENT_REVIEW_RULE_IDS: dict[str, tuple[str, ...]] = {
    "process": (
        "process.object.consistency",
        "process.type.boundary_match",
        "process.boundary.cutoff_and_exclusions",
        "process.inventory.boundary_consistency",
        "process.inventory.key_flow_completeness",
        "process.reference_flow.quantity_unit",
        "process.reference_flow.annual_supply_unit",
        "process.flow.semantic_match",
        "process.classification.process_fit",
        "process.description.source_content_attribution",
        "process.source.traceability",
        "process.representativeness.consistency",
        "process.metadata.dqr_completeness",
    ),
    "model": (
        "model.linked_process.audit",
    ),
}


def required_rule_ids(dataset_type: str) -> tuple[str, ...]:
    return REQUIRED_AGENT_REVIEW_RULE_IDS.get(dataset_type, ())


@dataclass(slots=True)
class AgentRuleReview:
    """One explicit Agent verdict for a judgment rule."""

    rule_id: str
    verdict: str
    location: str = ""
    evidence: str = ""
    judgment: str = ""
    suggestion: str = ""
    severity: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    platform: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "rule_id": self.rule_id,
            "verdict": self.verdict,
            "location": self.location,
            "evidence": self.evidence,
            "judgment": self.judgment,
            "suggestion": self.suggestion,
            "severity": self.severity,
            "evidence_refs": list(self.evidence_refs),
        }
        if self.platform is not None:
            payload["platform"] = dict(self.platform)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentRuleReview":
        raw_evidence_refs = payload.get("evidence_refs")
        evidence_refs = (
            [item for item in raw_evidence_refs if isinstance(item, str)]
            if isinstance(raw_evidence_refs, list)
            else []
        )
        return cls(
            rule_id=str(payload.get("rule_id") or ""),
            verdict=str(payload.get("verdict") or ""),
            location=str(payload.get("location") or ""),
            evidence=str(payload.get("evidence") or ""),
            judgment=str(payload.get("judgment") or ""),
            suggestion=str(payload.get("suggestion") or ""),
            severity=str(payload.get("severity") or ""),
            evidence_refs=evidence_refs,
            platform=(
                dict(payload["platform"])
                if isinstance(payload.get("platform"), dict)
                else payload.get("platform")
            ),
        )


def new_agent_findings_template(
    *,
    review_id: str,
    dataset_id: str = "",
    dataset_type: str = "",
) -> dict[str, Any]:
    """Scaffold an agent-findings.json with every required rule pending."""

    return {
        "schema_version": AGENT_FINDINGS_SCHEMA_VERSION,
        "review_id": review_id,
        "dataset_id": dataset_id,
        "dataset_type": dataset_type,
        "reviewed_by": "",
        "source_documents_read": [],
        "rule_reviews": [
            {
                "rule_id": rule_id,
                "verdict": "",
                "location": "",
                "evidence": "",
                "judgment": "",
                "suggestion": "",
                "severity": "",
                "evidence_refs": [],
                "platform": {"disposition": "internal_only"},
            }
            for rule_id in required_rule_ids(dataset_type)
        ],
        "additional_findings": [],
        "platform_overrides": [],
    }


def validate_agent_findings(
    payload: Any,
    *,
    dataset_type: str = "",
) -> list[str]:
    """Return human-readable contract violations; empty list means valid."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["agent findings payload must be a JSON object"]
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_AGENT_FINDINGS_SCHEMA_VERSIONS:
        errors.append(
            "schema_version must be one of "
            f"{sorted(SUPPORTED_AGENT_FINDINGS_SCHEMA_VERSIONS)}, got {schema_version!r}"
        )
    is_v1 = schema_version == AGENT_FINDINGS_SCHEMA_VERSION_V1
    top_level_fields = _TOP_LEVEL_FIELDS_V1 if is_v1 else _TOP_LEVEL_FIELDS_V2
    unknown_top_level = set(payload) - top_level_fields
    if unknown_top_level:
        suffix = " in v1" if is_v1 else ""
        errors.append(
            "top-level unknown properties"
            f"{suffix}: {', '.join(sorted(unknown_top_level))}"
        )
    if not str(payload.get("reviewed_by") or "").strip():
        errors.append("reviewed_by is required (agent identity or reviewer name)")

    rule_reviews = payload.get("rule_reviews")
    if not isinstance(rule_reviews, list):
        errors.append("rule_reviews must be a list")
        rule_reviews = []

    seen_rule_ids: set[str] = set()
    for index, item in enumerate(rule_reviews, 1):
        label = f"rule_reviews[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        rule_fields = _RULE_REVIEW_FIELDS_V1 if is_v1 else _RULE_REVIEW_FIELDS_V2
        unknown = set(item) - rule_fields
        if unknown:
            suffix = " in v1" if is_v1 else ""
            errors.append(
                f"{label}: unknown properties{suffix}: {', '.join(sorted(unknown))}"
            )
        raw_evidence_refs = item.get("evidence_refs", [])
        safe_item = item
        if not isinstance(raw_evidence_refs, list):
            errors.append(f"{label}: evidence_refs must be a list")
            safe_item = dict(item)
            safe_item["evidence_refs"] = []
        else:
            for ref_index, ref in enumerate(raw_evidence_refs, 1):
                if not isinstance(ref, str):
                    errors.append(
                        f"{label}: evidence_refs[{ref_index}] must be a string"
                    )
        review = AgentRuleReview.from_dict(safe_item)
        if not review.rule_id:
            errors.append(f"{label}: rule_id is required")
        if review.rule_id in seen_rule_ids:
            errors.append(f"{label}: duplicate rule_id {review.rule_id}")
        seen_rule_ids.add(review.rule_id)
        if review.verdict not in VALID_VERDICTS:
            errors.append(
                f"{label} ({review.rule_id}): verdict must be one of "
                f"{', '.join(VALID_VERDICTS)}; got {review.verdict!r}"
            )
            continue
        if review.verdict in {"pass", "fail"}:
            if not review.evidence.strip():
                errors.append(
                    f"{label} ({review.rule_id}): {review.verdict} verdict requires evidence"
                )
            if not review.evidence_refs:
                errors.append(
                    f"{label} ({review.rule_id}): {review.verdict} verdict requires "
                    "evidence_refs pointing at case files (dataset snapshot, source text, page)"
                )
        if review.verdict == "fail":
            if review.severity not in VALID_SEVERITIES:
                errors.append(
                    f"{label} ({review.rule_id}): fail verdict requires severity in "
                    f"{sorted(VALID_SEVERITIES)}"
                )
            if not review.suggestion.strip():
                errors.append(f"{label} ({review.rule_id}): fail verdict requires suggestion")
        if review.verdict in {"cannot_judge", "not_applicable"} and not review.judgment.strip():
            errors.append(
                f"{label} ({review.rule_id}): {review.verdict} verdict requires judgment "
                "explaining why"
            )
        if review.verdict in {"pass", "not_applicable"} and review.severity:
            errors.append(
                f"{label} ({review.rule_id}): {review.verdict} review must have empty "
                f"severity; got {review.severity!r}"
            )
        if review.verdict == "cannot_judge" and review.severity not in {"", "manual_review"}:
            errors.append(
                f"{label} ({review.rule_id}): cannot_judge uses fixed manual_review "
                f"severity; got {review.severity!r}"
            )
        if review.platform is not None:
            effective_severity = review.severity
            if review.verdict == "cannot_judge":
                effective_severity = "manual_review"
            try:
                parsed_platform = PlatformProjection.from_dict(review.platform)
            except ValueError as exc:
                parsed_platform = None
                projection_errors = [str(exc)]
            else:
                projection_errors = []
                if not (
                    parsed_platform.disposition == "internal_only"
                    and review.verdict in {"pass", "not_applicable"}
                ):
                    projection_errors = validate_platform_projection(
                        effective_severity, parsed_platform
                    )
            errors.extend(
                f"{label} ({review.rule_id}): {error}"
                for error in projection_errors
            )
            if (
                parsed_platform is not None
                and parsed_platform.disposition != "internal_only"
                and review.verdict in {"pass", "not_applicable"}
            ):
                errors.append(
                    f"{label} ({review.rule_id}): {review.verdict} review forbids "
                    "a non-internal platform projection"
                )

    additional = payload.get("additional_findings")
    if additional is None:
        additional = []
    if not isinstance(additional, list):
        errors.append("additional_findings must be a list")
        additional = []
    for index, item in enumerate(additional, 1):
        label = f"additional_findings[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        additional_fields = (
            _ADDITIONAL_FINDING_FIELDS_V1 if is_v1 else _ADDITIONAL_FINDING_FIELDS_V2
        )
        unknown = set(item) - additional_fields
        if unknown:
            suffix = " in v1" if is_v1 else ""
            errors.append(
                f"{label}: unknown properties{suffix}: {', '.join(sorted(unknown))}"
            )
        if str(item.get("severity") or "") not in VALID_SEVERITIES:
            errors.append(f"{label}: severity must be one of {sorted(VALID_SEVERITIES)}")
        for key in ("location", "evidence", "judgment", "suggestion"):
            if not str(item.get(key) or "").strip():
                errors.append(f"{label}: {key} is required")
        if "evidence_refs" in item:
            raw_evidence_refs = item.get("evidence_refs")
            if not isinstance(raw_evidence_refs, list):
                errors.append(f"{label}: evidence_refs must be a list")
            else:
                for ref_index, ref in enumerate(raw_evidence_refs, 1):
                    if not isinstance(ref, str):
                        errors.append(
                            f"{label}: evidence_refs[{ref_index}] must be a string"
                        )
        if item.get("platform") is not None:
            errors.extend(
                f"{label}: {error}"
                for error in validate_platform_projection(
                    str(item.get("severity") or ""), item.get("platform")
                )
            )

    overrides = payload.get("platform_overrides")
    if overrides is None:
        overrides = []
    if not isinstance(overrides, list):
        errors.append("platform_overrides must be a list")
        overrides = []
    seen_override_targets: set[tuple[str, str]] = set()
    for index, item in enumerate(overrides, 1):
        label = f"platform_overrides[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        unknown = set(item) - {"rule_id", "location", "platform"}
        if unknown:
            errors.append(
                f"{label}: unknown properties: {', '.join(sorted(unknown))}"
            )
        raw_rule_id = item.get("rule_id")
        raw_location = item.get("location")
        rule_id = raw_rule_id.strip() if isinstance(raw_rule_id, str) else ""
        location = raw_location.strip() if isinstance(raw_location, str) else ""
        if "rule_id" not in item:
            errors.append(f"{label}: rule_id is required")
        elif not isinstance(raw_rule_id, str):
            errors.append(f"{label}: rule_id must be a string")
        elif not rule_id:
            errors.append(f"{label}: rule_id is required")
        if "location" not in item:
            errors.append(f"{label}: location is required")
        elif not isinstance(raw_location, str):
            errors.append(f"{label}: location must be a string")
        elif not location:
            errors.append(f"{label}: location is required")
        target = (rule_id, location)
        if rule_id and location and target in seen_override_targets:
            errors.append(
                f"{label}: duplicate override target rule_id={rule_id!r}, "
                f"location={location!r}"
            )
        if rule_id and location:
            seen_override_targets.add(target)
        try:
            PlatformProjection.from_dict(item.get("platform"))
        except ValueError as exc:
            errors.append(f"{label}: {exc}")

    effective_type = dataset_type or str(payload.get("dataset_type") or "")
    missing = uncovered_required_rule_ids(payload, dataset_type=effective_type)
    if missing:
        errors.append(
            "missing required rule reviews: " + ", ".join(missing)
        )
    return errors


def uncovered_required_rule_ids(payload: Any, *, dataset_type: str) -> list[str]:
    """Required rule ids without an explicit verdict in the payload."""

    if not isinstance(payload, dict):
        return list(required_rule_ids(dataset_type))
    covered = {
        str(item.get("rule_id") or "")
        for item in payload.get("rule_reviews") or []
        if isinstance(item, dict) and str(item.get("verdict") or "") in VALID_VERDICTS
    }
    return [rule_id for rule_id in required_rule_ids(dataset_type) if rule_id not in covered]
