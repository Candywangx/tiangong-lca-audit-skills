from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .finding import VALID_SEVERITIES

AGENT_FINDINGS_SCHEMA_VERSION = "tiangong-audit-agent-findings-v1"
VALID_VERDICTS = ("pass", "fail", "cannot_judge", "not_applicable")

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "verdict": self.verdict,
            "location": self.location,
            "evidence": self.evidence,
            "judgment": self.judgment,
            "suggestion": self.suggestion,
            "severity": self.severity,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentRuleReview":
        return cls(
            rule_id=str(payload.get("rule_id") or ""),
            verdict=str(payload.get("verdict") or ""),
            location=str(payload.get("location") or ""),
            evidence=str(payload.get("evidence") or ""),
            judgment=str(payload.get("judgment") or ""),
            suggestion=str(payload.get("suggestion") or ""),
            severity=str(payload.get("severity") or ""),
            evidence_refs=[str(item) for item in payload.get("evidence_refs") or []],
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
            }
            for rule_id in required_rule_ids(dataset_type)
        ],
        "additional_findings": [],
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
    if payload.get("schema_version") != AGENT_FINDINGS_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {AGENT_FINDINGS_SCHEMA_VERSION}, "
            f"got {payload.get('schema_version')!r}"
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
        review = AgentRuleReview.from_dict(item)
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
        if str(item.get("severity") or "") not in VALID_SEVERITIES:
            errors.append(f"{label}: severity must be one of {sorted(VALID_SEVERITIES)}")
        for key in ("location", "evidence", "judgment", "suggestion"):
            if not str(item.get(key) or "").strip():
                errors.append(f"{label}: {key} is required")

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
