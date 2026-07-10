from __future__ import annotations

import json
from pathlib import Path

from tiangong_audit.contracts.agent_review import (
    AGENT_FINDINGS_SCHEMA_VERSION,
    REQUIRED_AGENT_REVIEW_RULE_IDS,
    new_agent_findings_template,
    required_rule_ids,
    uncovered_required_rule_ids,
    validate_agent_findings,
)

ROOT = Path(__file__).resolve().parents[1]


def _valid_payload(dataset_type: str = "process") -> dict:
    return {
        "schema_version": AGENT_FINDINGS_SCHEMA_VERSION,
        "review_id": "review-1",
        "dataset_id": "dataset-1",
        "dataset_type": dataset_type,
        "reviewed_by": "agent",
        "source_documents_read": ["sources/source-001/extracted.md"],
        "rule_reviews": [
            {
                "rule_id": rule_id,
                "verdict": "pass",
                "location": "过程信息",
                "evidence": "字段与 source 摘录一致。",
                "judgment": "满足规则。",
                "suggestion": "",
                "severity": "",
                "evidence_refs": ["sources/source-001/extracted.md:p3"],
            }
            for rule_id in required_rule_ids(dataset_type)
        ],
        "additional_findings": [],
    }


def test_valid_payload_passes_contract():
    assert validate_agent_findings(_valid_payload(), dataset_type="process") == []


def test_required_rule_ids_registered_in_rule_catalog():
    catalog_ids: set[str] = set()
    for name in ("common.json", "process.json", "model.json"):
        payload = json.loads(
            (ROOT / "skill/tiangong-lca-audit/rules" / name).read_text(encoding="utf-8")
        )
        catalog_ids.update(rule["id"] for rule in payload["rules"])
    for rule_ids in REQUIRED_AGENT_REVIEW_RULE_IDS.values():
        assert set(rule_ids) <= catalog_ids


def test_fail_verdict_requires_severity_suggestion_and_refs():
    payload = _valid_payload()
    payload["rule_reviews"][0].update(
        {"verdict": "fail", "severity": "", "suggestion": "", "evidence_refs": []}
    )
    errors = validate_agent_findings(payload, dataset_type="process")
    joined = "\n".join(errors)
    assert "requires severity" in joined
    assert "requires suggestion" in joined
    assert "requires evidence_refs" in joined


def test_pass_verdict_requires_evidence():
    payload = _valid_payload()
    payload["rule_reviews"][0]["evidence"] = ""
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("requires evidence" in error for error in errors)


def test_cannot_judge_requires_judgment():
    payload = _valid_payload()
    payload["rule_reviews"][0].update({"verdict": "cannot_judge", "judgment": ""})
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("requires judgment" in error for error in errors)


def test_missing_required_rule_is_reported():
    payload = _valid_payload()
    removed = payload["rule_reviews"].pop()
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any(removed["rule_id"] in error for error in errors)
    assert removed["rule_id"] in uncovered_required_rule_ids(
        payload, dataset_type="process"
    )


def test_reviewed_by_is_required():
    payload = _valid_payload()
    payload["reviewed_by"] = ""
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("reviewed_by" in error for error in errors)


def test_additional_findings_must_be_complete():
    payload = _valid_payload()
    payload["additional_findings"] = [{"severity": "blocking", "location": "x"}]
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("evidence is required" in error for error in errors)


def test_template_covers_required_rules_and_fails_until_filled():
    template = new_agent_findings_template(
        review_id="review-1", dataset_id="dataset-1", dataset_type="process"
    )
    assert {item["rule_id"] for item in template["rule_reviews"]} == set(
        required_rule_ids("process")
    )
    assert validate_agent_findings(template, dataset_type="process")


def test_model_dataset_requires_linked_process_audit():
    payload = _valid_payload(dataset_type="model")
    assert validate_agent_findings(payload, dataset_type="model") == []
    payload["rule_reviews"] = []
    errors = validate_agent_findings(payload, dataset_type="model")
    assert any("model.linked_process.audit" in error for error in errors)


def test_agent_findings_schema_asset_matches_contract():
    schema = json.loads(
        (
            ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["properties"]["schema_version"]["const"] == AGENT_FINDINGS_SCHEMA_VERSION
    verdicts = set(schema["$defs"]["rule_review"]["properties"]["verdict"]["enum"])
    assert verdicts == {"pass", "fail", "cannot_judge", "not_applicable"}
