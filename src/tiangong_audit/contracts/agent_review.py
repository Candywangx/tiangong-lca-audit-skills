from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

from .evidence_ref import EvidenceReferenceError, resolve_evidence_ref
from .finding import VALID_SEVERITIES
from .rule_catalog import RequiredRuleIds, load_rule_catalog, required_rule_ids

AGENT_FINDINGS_SCHEMA_VERSION = "tiangong-audit-agent-findings-v1"
VALID_VERDICTS = ("pass", "fail", "cannot_judge", "not_applicable")

# Compatibility export: reads the catalog on every lookup.
REQUIRED_AGENT_REVIEW_RULE_IDS = RequiredRuleIds()


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
    rules_dir: Path | None = None,
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
            for rule_id in required_rule_ids(dataset_type, rules_dir=rules_dir)
        ],
        "additional_findings": [],
    }


@dataclass(slots=True)
class AgentFindingsAdmission:
    """Admission boundary; semantic prose remains owned by the Agent.

    Record indexes are zero-based and preserve JSON pointer identity. File errors
    isolate every record; coverage errors alone do not invalidate other records.
    """

    file_errors: list[str] = field(default_factory=list)
    rule_review_errors: dict[int, list[str]] = field(default_factory=dict)
    additional_finding_errors: dict[int, list[str]] = field(default_factory=dict)
    accepted_rule_review_indexes: list[int] = field(default_factory=list)
    accepted_additional_finding_indexes: list[int] = field(default_factory=list)
    missing_required_rule_ids: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        errors = [*self.file_errors]
        for collection in (self.rule_review_errors, self.additional_finding_errors):
            for record_errors in collection.values():
                errors.extend(record_errors)
        if self.missing_required_rule_ids:
            errors.append("missing required rule reviews: " + ", ".join(self.missing_required_rule_ids))
        return errors


def admit_agent_findings(payload: Any, *, dataset_type: str = "", rules_dir: Path | None = None, case_root: Path | None = None, expected_review_id: str | None = None, expected_dataset_id: str | None = None) -> AgentFindingsAdmission:
    """Validate file and individual records before formal aggregation.

    Without case_root this validates structure only; formal review supplies the
    case root and expected identity to resolve evidence before aggregation.
    """
    result = AgentFindingsAdmission()
    if not isinstance(payload, dict):
        result.file_errors.append("agent findings payload must be a JSON object")
        result.missing_required_rule_ids = list(required_rule_ids(dataset_type, rules_dir=rules_dir))
        return result
    if payload.get("schema_version") != AGENT_FINDINGS_SCHEMA_VERSION:
        result.file_errors.append(
            f"schema_version must be {AGENT_FINDINGS_SCHEMA_VERSION}, got {payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get("reviewed_by"), str) or not payload["reviewed_by"].strip():
        result.file_errors.append("reviewed_by is required (agent identity or reviewer name)")
    if dataset_type and payload.get("dataset_type") != dataset_type:
        result.file_errors.append(f"dataset_type must match {dataset_type!r}")
    for key, expected in (("review_id", expected_review_id), ("dataset_id", expected_dataset_id)):
        if expected is not None and payload.get(key) != expected:
            result.file_errors.append(f"{key} must match current case {expected!r}")
    for key in ("rule_reviews", "additional_findings"):
        value = payload.get(key, [] if key == "additional_findings" else None)
        if not isinstance(value, list):
            result.file_errors.append(f"{key} must be a list")
    if not isinstance(payload.get("source_documents_read", []), list):
        result.file_errors.append("source_documents_read must be a list")

    reviews = payload.get("rule_reviews")
    reviews = reviews if isinstance(reviews, list) else []
    additional = payload.get("additional_findings", [])
    additional = additional if isinstance(additional, list) else []
    effective_type = dataset_type or str(payload.get("dataset_type") or "")
    if effective_type not in {"process", "model"}:
        result.file_errors.append("dataset_type must identify process or model before a complete review")
    catalog = load_rule_catalog(effective_type, rules_dir=rules_dir)
    ids: dict[str, list[int]] = {}
    for index, item in enumerate(reviews):
        errors: list[str] = []
        label = f"rule_reviews[{index + 1}]"
        if not isinstance(item, dict):
            result.rule_review_errors[index] = [f"{label} must be an object"]
            continue
        rule_id = item.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            errors.append(f"{label}: rule_id is required")
        else:
            ids.setdefault(rule_id, []).append(index)
        verdict = item.get("verdict")
        if not isinstance(verdict, str) or verdict not in VALID_VERDICTS:
            errors.append(f"{label} ({rule_id}): verdict must be one of {', '.join(VALID_VERDICTS)}; got {verdict!r}")
        else:
            if verdict in {"pass", "fail", "not_applicable"}:
                if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
                    errors.append(f"{label} ({rule_id}): {verdict} verdict requires evidence")
                refs = item.get("evidence_refs")
                if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and ref.strip() for ref in refs):
                    errors.append(f"{label} ({rule_id}): {verdict} verdict requires evidence_refs pointing at case files (dataset snapshot, source text, page)")
                elif case_root is not None:
                    errors.extend(_resolve_refs(refs, case_root, label))
            if verdict == "not_applicable" and not (isinstance(rule_id, str) and catalog.get(rule_id, {}).get("allow_not_applicable", False)):
                errors.append(f"{label} ({rule_id}): rule does not allow not_applicable; use cannot_judge when evidence is insufficient")
            if verdict == "fail":
                if not isinstance(item.get("severity"), str) or item["severity"] not in VALID_SEVERITIES:
                    errors.append(f"{label} ({rule_id}): fail verdict requires severity in {sorted(VALID_SEVERITIES)}")
                if not isinstance(item.get("suggestion"), str) or not item["suggestion"].strip():
                    errors.append(f"{label} ({rule_id}): fail verdict requires suggestion")
            if verdict in {"cannot_judge", "not_applicable"}:
                if not isinstance(item.get("judgment"), str) or not item["judgment"].strip():
                    errors.append(f"{label} ({rule_id}): {verdict} verdict requires judgment explaining why")
            if verdict == "cannot_judge" and item.get("severity") not in (None, "", "manual_review", "input_gap"):
                errors.append(f"{label} ({rule_id}): cannot_judge severity must be blank, manual_review, or input_gap")
        if "evidence_refs" in item and not isinstance(item["evidence_refs"], list):
            errors.append(f"{label}: evidence_refs must be a list")
        if errors:
            result.rule_review_errors[index] = errors
    for rule_id, indexes in ids.items():
        if len(indexes) > 1:
            for index in indexes:
                result.rule_review_errors.setdefault(index, []).append(
                    f"rule_reviews[{index + 1}]: duplicate rule_id {rule_id}"
                )
    for index, item in enumerate(additional):
        errors = []
        label = f"additional_findings[{index + 1}]"
        if not isinstance(item, dict):
            result.additional_finding_errors[index] = [f"{label} must be an object"]
            continue
        if not isinstance(item.get("severity"), str) or item["severity"] not in VALID_SEVERITIES:
            errors.append(f"{label}: severity must be one of {sorted(VALID_SEVERITIES)}")
        for key in ("location", "evidence", "judgment", "suggestion"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append(f"{label}: {key} is required")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and ref.strip() for ref in refs):
            errors.append(f"{label}: requires evidence_refs pointing at case files")
        elif case_root is not None:
            errors.extend(_resolve_refs(refs, case_root, label))
        if errors:
            result.additional_finding_errors[index] = errors
    if not result.file_errors:
        result.accepted_rule_review_indexes = [i for i in range(len(reviews)) if i not in result.rule_review_errors]
        result.accepted_additional_finding_indexes = [i for i in range(len(additional)) if i not in result.additional_finding_errors]
    covered = {reviews[i]["rule_id"] for i in result.accepted_rule_review_indexes}
    result.missing_required_rule_ids = [rule_id for rule_id in required_rule_ids(effective_type, rules_dir=rules_dir) if rule_id not in covered]
    return result


def validate_agent_findings(payload: Any, *, dataset_type: str = "", rules_dir: Path | None = None, case_root: Path | None = None, expected_review_id: str | None = None, expected_dataset_id: str | None = None) -> list[str]:
    """Compatibility API returning all human-readable admission errors."""
    return admit_agent_findings(payload, dataset_type=dataset_type, rules_dir=rules_dir, case_root=case_root, expected_review_id=expected_review_id, expected_dataset_id=expected_dataset_id).errors


def uncovered_required_rule_ids(payload: Any, *, dataset_type: str, rules_dir: Path | None = None) -> list[str]:
    """Required ids without a valid, admitted explicit review."""
    return admit_agent_findings(payload, dataset_type=dataset_type, rules_dir=rules_dir).missing_required_rule_ids


def _resolve_refs(refs: list[str], case_root: Path, label: str) -> list[str]:
    errors = []
    for ref in refs:
        try:
            resolve_evidence_ref(ref, case_root=case_root)
        except EvidenceReferenceError as error:
            errors.append(f"{label}: invalid evidence_ref {ref!r}: {error}")
    return errors
